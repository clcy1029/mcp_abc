import asyncio
import json
from typing import Dict, List, TypedDict, Annotated, Literal
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
import openai


# ============ MCP Agent (完整版, 包含后台任务) ============
class MCPAgent:
    def __init__(self, server_module: str):
        self.server_module = server_module
        self.process = None
        self.tools = []
        self._tasks = []  # ⭐ 后台任务列表
        self._running = False
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._request_id = 0

    async def start(self):
        """启动MCP Server连接"""
        self.process = await asyncio.create_subprocess_exec(
            "python",
            "-m",
            self.server_module,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        self._running = True

        # ⭐ 启动3个后台任务 (必须!)
        self._tasks.append(asyncio.create_task(self._stdout_listener()))
        self._tasks.append(asyncio.create_task(self._heartbeat()))
        self._tasks.append(asyncio.create_task(self._metrics_pusher()))

        # 初始化获取工具列表
        await self._initialize()

    async def stop(self):
        """清理"""
        self._running = False
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self.process:
            self.process.kill()
            await self.process.wait()

    # ⭐ 核心: stdout监听器 (必须!)
    async def _stdout_listener(self):
        """持续读取MCP Server输出"""
        while self._running:
            try:
                line = await self.process.stdout.readline()
                if not line:
                    break

                msg = json.loads(line.decode())

                # 处理response
                if "id" in msg and msg["id"] in self._pending_requests:
                    fut = self._pending_requests.pop(msg["id"])
                    if not fut.done():
                        fut.set_result(msg)

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"stdout listener error: {e}")

    async def _heartbeat(self):
        """心跳"""
        while self._running:
            try:
                if self.process:
                    ping = {"type": "ping"}
                    self.process.stdin.write(json.dumps(ping).encode() + b"\n")
                    await self.process.stdin.drain()
            except Exception as e:
                print(f"heartbeat error: {e}")
            await asyncio.sleep(5)

    async def _metrics_pusher(self):
        """指标"""
        while self._running:
            try:
                print(f"[Metrics] Agent alive, tools: {len(self.tools)}")
            except Exception as e:
                print(f"metrics error: {e}")
            await asyncio.sleep(10)

    async def _initialize(self):
        request = {"jsonrpc": "2.0", "method": "tools/list"}
        response = await self._send_request(request)
        self.tools = response.get("result", {}).get("tools", [])

    async def _send_request(self, request: Dict) -> Dict:
        self._request_id += 1
        request["id"] = self._request_id

        fut = asyncio.get_running_loop().create_future()
        self._pending_requests[request["id"]] = fut

        self.process.stdin.write(json.dumps(request).encode() + b"\n")
        await self.process.stdin.drain()

        return await fut  # ⭐ 由_stdout_listener填充结果

    async def call_tool(self, name: str, args: Dict) -> Dict:
        request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": name, "arguments": args},
        }
        response = await self._send_request(request)
        return response.get("result")


# ============ LangGraph 状态定义 ============
class AgentState(TypedDict):
    messages: Annotated[List[Dict], add_messages]
    tool_calls: List[Dict]
    tool_results: List[Dict]
    next: str


# ============ LangGraph 节点 ============
class LangGraphMCPAgent:
    def __init__(self, mcp_agent: MCPAgent):
        self.mcp = mcp_agent
        self._setup_graph()

    def _setup_graph(self):
        workflow = StateGraph(AgentState)

        workflow.add_node("llm", self.call_llm)
        workflow.add_node("execute_tools", self.execute_tools)
        workflow.add_node("respond", self.respond)

        workflow.set_entry_point("llm")
        workflow.add_conditional_edges(
            "llm", self.should_continue, {"continue": "execute_tools", "end": "respond"}
        )
        workflow.add_edge("execute_tools", "llm")
        workflow.add_edge("respond", END)

        self.graph = workflow.compile()

    async def call_llm(self, state: AgentState) -> AgentState:
        """调用LLM决定使用哪个工具"""
        tools_desc = "\n".join(
            [f"- {t['name']}: {t.get('description', '')}" for t in self.mcp.tools]
        )

        last_message = state["messages"][-1]["content"]

        prompt = f"""你是一个智能助手，可以使用以下工具:
{tools_desc}

用户问题: {last_message}

如果需要使用工具，返回JSON格式:
{{"tool": "工具名", "args": {{}}}}

否则直接回答用户问题。
"""

        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )

        llm_output = response.choices[0].message.content

        try:
            tool_call = json.loads(llm_output)
            if "tool" in tool_call:
                state["tool_calls"] = [tool_call]
                state["next"] = "continue"
            else:
                state["messages"].append({"role": "assistant", "content": llm_output})
                state["next"] = "end"
        except:
            state["messages"].append({"role": "assistant", "content": llm_output})
            state["next"] = "end"

        return state

    async def execute_tools(self, state: AgentState) -> AgentState:
        """执行MCP工具调用"""
        results = []
        for tool_call in state.get("tool_calls", []):
            try:
                result = await self.mcp.call_tool(
                    tool_call["tool"], tool_call.get("args", {})
                )
                results.append({"tool": tool_call["tool"], "result": result})
            except Exception as e:
                results.append({"tool": tool_call["tool"], "error": str(e)})

        state["tool_results"] = results
        for r in results:
            state["messages"].append(
                {
                    "role": "system",
                    "content": f"工具 {r['tool']} 返回: {r.get('result', r.get('error'))}",
                }
            )

        return state

    async def respond(self, state: AgentState) -> AgentState:
        return state

    def should_continue(self, state: AgentState) -> Literal["continue", "end"]:
        return state.get("next", "end")

    async def chat(self, message: str) -> str:
        initial_state = {
            "messages": [{"role": "user", "content": message}],
            "tool_calls": [],
            "tool_results": [],
            "next": "",
        }

        final_state = await self.graph.ainvoke(initial_state)

        for msg in reversed(final_state["messages"]):
            if msg["role"] == "assistant":
                return msg["content"]

        return "处理完成"


# ============ 主程序 ============
async def main():
    # 1. 启动MCP Agent (包含3个后台任务)
    mcp = MCPAgent("mcp-server-weather")
    await mcp.start()
    print(f"可用工具: {[t['name'] for t in mcp.tools]}")

    try:
        # 2. 创建LangGraph Agent
        agent = LangGraphMCPAgent(mcp)

        # 3. 对话
        response = await agent.chat("北京今天多少度？")
        print(f"助手: {response}")

        response = await agent.chat("上海呢？")
        print(f"助手: {response}")

        await asyncio.sleep(30)  # 模拟运行

    finally:
        # 4. 清理
        await mcp.stop()


if __name__ == "__main__":
    asyncio.run(main())
