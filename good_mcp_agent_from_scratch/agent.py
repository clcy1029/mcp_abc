import subprocess
import json
import asyncio
from typing import Dict, Any, List
import openai


class ManualMCPAgent:
    def __init__(self, server_module: str):
        self.server_module = server_module
        self.process = None
        self.tools: List[Dict] = []

        # ⭐ background task 管理
        self._tasks: List[asyncio.Task] = []
        self._running = False

        # ⭐ request-response 同步
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._request_id = 0

    # ==============================
    # Lifecycle
    # ==============================
    async def start_server(self):
        self.process = await asyncio.create_subprocess_exec(
            "python",
            "-m",
            self.server_module,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        self._running = True

        # ⭐ 启动后台 worker
        self._tasks.append(asyncio.create_task(self._stdout_listener()))
        self._tasks.append(asyncio.create_task(self._heartbeat()))
        self._tasks.append(asyncio.create_task(self._metrics_pusher()))

        await self._initialize()

    async def stop(self):
        self._running = False

        for t in self._tasks:
            t.cancel()

        await asyncio.gather(*self._tasks, return_exceptions=True)

        if self.process:
            self.process.kill()
            await self.process.wait()

    # ==============================
    # Background Workers
    # ==============================
    async def _stdout_listener(self):
        """持续读取 MCP server 输出"""
        while self._running:
            try:
                line = await self.process.stdout.readline()
                if not line:
                    break

                msg = json.loads(line.decode())

                # ⭐ 处理 response
                if "id" in msg and msg["id"] in self._pending_requests:
                    fut = self._pending_requests.pop(msg["id"])
                    if not fut.done():
                        fut.set_result(msg)

                # ⭐ 处理 server push event（如果有）
                elif msg.get("method"):
                    print("[Server Event]", msg)

            except asyncio.CancelledError:
                break
            except Exception as e:
                print("stdout listener error:", e)

    async def _heartbeat(self):
        while self._running:
            try:
                if self.process:
                    ping = {"type": "ping"}
                    self.process.stdin.write((json.dumps(ping) + "\n").encode())
                    await self.process.stdin.drain()

            except Exception as e:
                print("heartbeat error:", e)

            await asyncio.sleep(5)

    async def _metrics_pusher(self):
        while self._running:
            try:
                print("[Metrics] agent alive")

            except Exception as e:
                print("metrics error:", e)

            await asyncio.sleep(10)

    # ==============================
    # MCP RPC
    # ==============================
    async def _initialize(self):
        request = {
            "jsonrpc": "2.0",
            "method": "tools/list",
        }

        response = await self._send_request(request)
        self.tools = response.get("result", {}).get("tools", [])
        print(f"已加载工具: {[t['name'] for t in self.tools]}")

    async def _send_request(self, request: Dict) -> Dict:
        self._request_id += 1
        request_id = self._request_id
        request["id"] = request_id

        fut = asyncio.get_running_loop().create_future()
        self._pending_requests[request_id] = fut

        self.process.stdin.write((json.dumps(request) + "\n").encode())
        await self.process.stdin.drain()

        return await fut

    async def call_tool(self, tool_name: str, arguments: Dict):
        request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }

        response = await self._send_request(request)

        if "error" in response:
            raise Exception(response["error"])

        return response.get("result")

    # ==============================
    # LLM Chat
    # ==============================
    async def chat(self, user_message: str) -> str:
        tools_desc = "\n".join(
            [f"- {t['name']}: {t.get('description', '无描述')}" for t in self.tools]
        )

        prompt = f"""
你是一个智能助手，可以使用以下工具：
{tools_desc}

用户问题：{user_message}

如果需要使用工具，请返回JSON：
{{"tool": "...", "args": {{}}}}
否则直接回答。
"""

        # ⭐ 注意：真实生产这里应该用 async client
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )

        llm_output = response.choices[0].message.content

        try:
            tool_call = json.loads(llm_output)
            if "tool" in tool_call:
                result = await self.call_tool(
                    tool_call["tool"], tool_call.get("args", {})
                )
                return f"工具调用结果: {result}"
        except Exception:
            pass

        return llm_output


# ==============================
# Main
# ==============================
async def main():
    agent = ManualMCPAgent("mcp-server-weather")

    try:
        await agent.start_server()

        r1 = await agent.chat("北京今天多少度？")
        print(r1)

        r2 = await agent.chat("上海呢？")
        print(r2)

        await asyncio.sleep(30)  # 模拟服务运行

    finally:
        await agent.stop()


async def main_concurrent():
    agent = ManualMCPAgent("mcp-server-weather")
    await agent.start_server()

    # ═════ 并行执行 ═════
    task1 = asyncio.create_task(agent.chat("北京天气"))
    task2 = asyncio.create_task(agent.chat("上海天气"))
    # 北京和上海的请求几乎同时发出！

    r1 = await task1  # 等待北京完成
    r2 = await task2  # 等待上海完成
    print(r1, r2)


if __name__ == "__main__":

    # 顺序
    asyncio.run(main())

    # 并发
    # asyncio.run(main_concurrent())
