# MCP 架构简明总结

## 一、核心架构图

```
┌─────────────────────────────────────────────────────────────┐
│                        MCP Client/Agent                     │
│  (Claude Desktop, Cursor, Windsurf, 或你自己的Agent)        │
│                                                             │
│  ┌─────────────────┐    ┌─────────────────┐               │
│  │   Transport层   │    │   Session层     │               │
│  │  (stdio/HTTP)   │◄──►│  (协议处理)     │               │
│  └─────────────────┘    └─────────────────┘               │
│           ▲                       ▲                       │
└───────────┼───────────────────────┼───────────────────────┘
            │                       │
            │  stdin/stdout         │  HTTP/SSE
            │  (本地进程)           │  (远程服务)
            ▼                       ▼
┌───────────────────────┐  ┌───────────────────────┐
│  本地 MCP Server       │  │  远程 MCP Server      │
│  (你手写的server.py)   │  │  (DeepWiki, 腾讯等)   │
│                       │  │                       │
│  @mcp.tool()          │  │  https://api.xxx/mcp │
│  def get_weather():   │  │  POST /jsonrpc        │
└───────────────────────┘  └───────────────────────┘
```

---

## 二、支持的传输协议

| 协议 | 通信方式 | 适用场景 | 配置示例 | 典型代表 |
|------|---------|---------|---------|---------|
| **stdio** | 标准输入/输出 | 本地进程、同主机 | `"command": "python", "args": ["server.py"]` | Filesystem, GitHub, Playwright |
| **Streamable HTTP** | HTTP POST (新标准) | 远程服务、云托管 | `"serverUrl": "https://api.com/mcp"` | DeepWiki, 腾讯RTC |
| **SSE** | Server-Sent Events (旧) | 实时推送、正在淘汰 | `"url": "https://api.com/sse"` | 老版本服务 |

**一句话选型：**
- 本地工具 → **stdio**
- 云端服务 → **Streamable HTTP**（**千万别选 SSE**，已废弃）

---

## 三、两种连接模式对比

### 模式A：本地 stdio（你手写的那种）
```
你的Agent ── stdin ──► MCP Server (子进程)
        ◄── stdout ──
        
特点：
✅ 无需网络，低延迟
✅ 适合文件系统、数据库、本地工具
✅ 进程生命周期由Agent管理
❌ 每Server一个子进程
❌ 无法直接连云端服务
```

**配置方式：**
```json
{
  "mcpServers": {
    "my-server": {
      "command": "python",
      "args": ["-m", "my_mcp_server"]
    }
  }
}
```

**代码实现（官方SDK）：**
```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

server_params = StdioServerParameters(command="python", args=["server.py"])
async with stdio_client(server_params) as (read, write):
    async with ClientSession(read, write) as session:
        await session.call_tool(...)  # 一行调用
```

---

### 模式B：远程 HTTP（现代MCP）
```
你的Agent ── HTTP POST ──► MCP Server (云端)
        ◄── HTTP Response ──
        
特点：
✅ 无需本地进程
✅ 一个Client连任意多Server
✅ Server由Provider托管
✅ 适合SaaS服务（DeepWiki、Slack、GitHub）
```

**配置方式：**
```json
{
  "mcpServers": {
    "deepwiki": {
      "serverUrl": "https://mcp.deepwiki.com/mcp"
    }
  }
}
```

**代码实现（官方SDK实验性）：**
```python
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

async with streamable_http_client("https://mcp.deepwiki.com/mcp") as streams:
    async with ClientSession(streams[0], streams[1]) as session:
        await session.call_tool(...)  # 接口完全一样！
```

---

## 四、你的手写Agent vs 官方SDK

| 功能 | 你手写 `ManualMCPAgent` | 官方 SDK |
|------|----------------------|---------|
| **stdio 支持** | ✅ 200+行代码 | ✅ 3行代码 |
| **HTTP 支持** | ❌ 完全不能 | ✅ 实验性支持 |
| **SSE 支持** | ❌ 完全不能 | ✅ 但已废弃 |
| **Future + ID匹配** | ✅ 自己实现 | ✅ 内置 |
| **后台监听** | ✅ `_stdout_listener` | ✅ 内置 |
| **进程管理** | ✅ `create_subprocess` | ✅ `stdio_client` 自动管理 |
| **初始化握手** | ✅ `_initialize()` | ✅ `session.initialize()` 自动 |
| **多Server管理** | ❌ 每个Agent一个 | ✅ 一个Client多个Session |

**结论：** 你的手写 Agent 是**极好的 stdio 教学实现**，但**生产环境请用官方 SDK**——它让你**一行代码切换 stdio/HTTP**，不用重写通信层。

---

## 五、真实世界连线案例

### 场景1：本地文件系统 + 云端DeepWiki
```python
import asyncio
from mcp import ClientSession
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

async def main():
    # 1. 连本地 stdio server (文件系统)
    fs_params = StdioServerParameters(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "."]
    )
    async with stdio_client(fs_params) as (r1, w1):
        async with ClientSession(r1, w1) as fs:
            await fs.initialize()
            files = await fs.call_tool("list_directory", arguments={"path": "."})
    
    # 2. 连远程 HTTP server (DeepWiki)
    async with streamable_http_client("https://mcp.deepwiki.com/mcp") as (r2, w2):
        async with ClientSession(r2, w2) as wiki:
            await wiki.initialize()
            answer = await wiki.call_tool(
                "ask_question",
                arguments={"repo": "owner/repo", "question": "如何配置？"}
            )
    
    # 接口完全一致！只有 transport 不同
```

---

## 六、一句话总结

**MCP 是 AI 应用的 USB-C：**
- **stdio** = 本地外设（你的手写 Agent 就是自制USB线）
- **HTTP** = 云端服务（官方SDK是品牌充电头）
- **官方 SDK** = 一根线走天下，换协议不改代码

**你的 `ManualMCPAgent` 让你理解了 USB 协议原理。现在可以用官方 SDK 愉快地插拔各种 MCP 设备了。** 🔌