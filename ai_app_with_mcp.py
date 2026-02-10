"""
AI App with Multiple MCP Servers - Complete Example
Demonstrates how an AI application handles multiple MCP servers with callbacks
"""

import subprocess
import json
import threading
import time
from typing import Dict, Callable, Optional
import random


class MyAIAgent:
    """
    AI Agent that manages multiple MCP servers and handles concurrent responses
    Key concepts demonstrated:
    1. Each MCP server runs in its own subprocess with independent pipes
    2. Callbacks are stored as Python function objects (not JSON/code)
    3. Listener threads run in background to monitor server responses
    4. Main thread remains responsive for user interaction
    5. Thread locking protects shared data structures
    """

    def __init__(self):
        # Store MCP server subprocesses
        self.mcp_servers: Dict[str, subprocess.Popen] = {}

        # Track pending requests: request_id -> {"server": name, "callback": func}
        self.pending_requests: Dict[int, dict] = {}

        # Counter for unique request IDs
        self.request_counter = 1

        # Lock for thread-safe access to shared data
        self.lock = threading.Lock()

        # Results queue for UI updates
        self.results_queue = []

        print("🤖 AI Agent initialized")

    def start_mcp_servers(self):
        """
        Start multiple MCP servers as independent subprocesses.
        Each server gets its own set of stdin/stdout/stderr pipes.
        """
        print("🚀 Starting MCP servers...")

        # Start Weather MCP Server
        weather_proc = subprocess.Popen(
            ["python", "weather_mcp.py"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.mcp_servers["weather"] = weather_proc

        # Start Stock MCP Server
        stock_proc = subprocess.Popen(
            ["python", "stock_mcp.py"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.mcp_servers["stock"] = stock_proc

        # Start a listener thread for each server
        for server_name, proc in self.mcp_servers.items():
            listener_thread = threading.Thread(
                target=self._listen_to_server,
                args=(server_name, proc),
                daemon=True,  # Thread exits when main program exits
            )
            listener_thread.start()
            print(f"   👂 Listener started for {server_name} server")

        print("✅ All MCP servers started")

    def ask_question(self, question: str):
        """
        Main entry point for user questions.
        Runs in the main thread and returns immediately (non-blocking).
        """
        print(f"\n👤 User: {question}")

        # Simple question routing
        if "weather" in question.lower() or "天气" in question:
            if "beijing" in question.lower() or "北京" in question:
                self._get_beijing_weather()
            elif "shanghai" in question.lower() or "上海" in question:
                self._get_shanghai_weather()
        elif "stock" in question.lower() or "股价" in question:
            if "apple" in question.lower() or "苹果" in question:
                self._get_apple_stock()
            elif "tesla" in question.lower() or "特斯拉" in question:
                self._get_tesla_stock()
        else:
            print("❌ I don't understand that question")

    # ========== CALLBACK DEFINITIONS (created in main thread) ==========

    def _get_beijing_weather(self):
        """Example: Get Beijing weather with callback"""
        print("📡 Querying Beijing weather...")

        # 🔑 Callback is defined HERE in main thread as a Python function object
        def handle_beijing_weather(result: dict):
            """This callback will execute later in listener thread"""
            weather_text = result.get("content", [{}])[0].get("text", "No data")
            print(f"✅ Beijing weather callback executed: {weather_text}")

            # Update UI (in real app, this would trigger UI update)
            self._update_ui(f"Beijing: {weather_text}")

            # Can trigger further actions
            if "sunny" in weather_text.lower():
                self._suggest_action(
                    "It's sunny in Beijing! Good day for outdoor activities."
                )

        # Make the MCP call with callback
        self._call_mcp_tool(
            server_name="weather",
            tool_name="get_weather",
            arguments={"city": "Beijing"},
            callback=handle_beijing_weather,  # 🔑 Passing function object, not code
        )

    def _get_shanghai_weather(self):
        """Example: Get Shanghai weather with callback"""
        print("📡 Querying Shanghai weather...")

        def handle_shanghai_weather(result: dict):
            weather_text = result.get("content", [{}])[0].get("text", "No data")
            print(f"✅ Shanghai weather callback executed: {weather_text}")
            self._update_ui(f"Shanghai: {weather_text}")

        self._call_mcp_tool(
            server_name="weather",
            tool_name="get_weather",
            arguments={"city": "Shanghai"},
            callback=handle_shanghai_weather,
        )

    def _get_apple_stock(self):
        """Example: Get Apple stock price with callback"""
        print("📈 Querying Apple stock...")

        def handle_apple_stock(result: dict):
            stock_text = result.get("content", [{}])[0].get("text", "No data")
            print(f"✅ Apple stock callback executed: {stock_text}")
            self._update_ui(f"AAPL: {stock_text}")

            # Example: Make decision based on price
            if "182" in stock_text:
                self._suggest_action("AAPL at good price, consider buying")

        self._call_mcp_tool(
            server_name="stock",
            tool_name="get_stock_price",
            arguments={"symbol": "AAPL"},
            callback=handle_apple_stock,
        )

    def _get_tesla_stock(self):
        """Example: Get Tesla stock price with callback"""
        print("📈 Querying Tesla stock...")

        def handle_tesla_stock(result: dict):
            stock_text = result.get("content", [{}])[0].get("text", "No data")
            print(f"✅ Tesla stock callback executed: {stock_text}")
            self._update_ui(f"TSLA: {stock_text}")

            if "175" in stock_text:
                self._suggest_action("TSLA price low, maybe wait")

        self._call_mcp_tool(
            server_name="stock",
            tool_name="get_stock_price",
            arguments={"symbol": "TSLA"},
            callback=handle_tesla_stock,
        )

    # ========== CORE COMMUNICATION LOGIC ==========

    def _call_mcp_tool(
        self, server_name: str, tool_name: str, arguments: dict, callback: Callable
    ) -> Optional[int]:
        """
        Call an MCP tool (NON-BLOCKING).

        Args:
            server_name: Which MCP server to use
            tool_name: Tool to call
            arguments: Arguments for the tool
            callback: Python function to execute when response arrives

        Returns:
            Request ID or None if failed
        """
        if server_name not in self.mcp_servers:
            print(f"❌ Server '{server_name}' not found")
            return None

        # Generate unique request ID with thread protection
        with self.lock:
            request_id = self.request_counter
            self.request_counter += 1

            # 🔑 Store callback as Python function object in dictionary
            self.pending_requests[request_id] = {
                "server": server_name,
                "callback": callback,  # This is the function object
                "created_at": time.time(),
            }

        # Prepare JSON-RPC request
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }

        # Send to MCP server via its stdin pipe
        proc = self.mcp_servers[server_name]
        proc.stdin.write(json.dumps(request) + "\n")
        proc.stdin.flush()

        print(f"📤 Sent request to {server_name} (ID: {request_id})")
        return request_id

    def _listen_to_server(self, server_name: str, proc: subprocess.Popen):
        """
        Listen thread function - monitors one server's stdout pipe.
        Runs in BACKGROUND THREAD, not main thread.
        """
        print(
            f"   🧵 Listener for {server_name} started in thread: {threading.get_ident()}"
        )

        try:
            while proc.poll() is None:  # While process is alive
                # Read from server's stdout pipe (blocks until data arrives)
                line = proc.stdout.readline()
                if not line:
                    break  # Pipe closed

                # Process the response
                self._handle_server_response(server_name, line)

        except Exception as e:
            print(f"⚠️  Listener for {server_name} error: {e}")

        print(f"⚠️  Listener for {server_name} stopped")

    def _handle_server_response(self, server_name: str, response_line: str):
        """
        Handle response from MCP server.
        Executes in LISTENER THREAD, not main thread.
        """
        try:
            # Parse JSON-RPC response
            response = json.loads(response_line)
            request_id = response.get("id")

            # Thread-safe access to pending requests
            with self.lock:
                if request_id not in self.pending_requests:
                    print(f"⚠️  Unknown request ID: {request_id}")
                    return

                pending = self.pending_requests[request_id]

                # Verify response came from correct server
                if pending["server"] != server_name:
                    print(
                        f"⚠️  Server mismatch! Expected {pending['server']}, got {server_name}"
                    )
                    return

                # 🔑 Get the callback function object
                callback = pending["callback"]

                # Remove from pending requests
                del self.pending_requests[request_id]

            # 🎯 EXECUTE THE CALLBACK (in listener thread!)
            print(
                f"🔗 Executing callback for request {request_id} in thread {threading.get_ident()}"
            )

            # Pass the result data to the callback
            callback(response.get("result", {}))

            # ⚠️ If callback takes long, this thread is blocked!
            # In production, you might want: threading.Thread(target=callback, args=(result,)).start()

        except json.JSONDecodeError:
            print(f"[{server_name} raw] {response_line.strip()}")
        except Exception as e:
            print(f"❌ Error handling response: {e}")

    # ========== HELPER METHODS ==========

    def _update_ui(self, message: str):
        """Simulate UI update"""
        self.results_queue.append(message)
        print(f"💻 UI Updated: {message}")

    def _suggest_action(self, suggestion: str):
        """Simulate action suggestion"""
        print(f"💡 Suggestion: {suggestion}")

    def cleanup(self):
        """Clean up all server processes"""
        print("\n🧹 Cleaning up...")
        for name, proc in self.mcp_servers.items():
            if proc.poll() is None:
                proc.terminate()
                print(f"   Stopped {name} server")


# ========== SIMULATED MCP SERVERS ==========

WEATHER_MCP_CODE = '''
"""
Simulated Weather MCP Server
Responds with random weather data
"""
import sys, json, time, random

print("🌤️  Weather MCP Server started", file=sys.stderr)

while True:
    try:
        line = sys.stdin.readline()
        if not line:
            break
        
        request = json.loads(line)
        
        if request["method"] == "tools/call":
            city = request["params"]["arguments"]["city"]
            
            # Simulate API delay
            delay = random.uniform(0.3, 1.2)
            time.sleep(delay)
            
            # Generate random weather
            temp = random.randint(15, 30)
            conditions = ["sunny", "cloudy", "rainy", "windy"]
            condition = random.choice(conditions)
            
            response = {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": {
                    "content": [{
                        "type": "text",
                        "text": f"{city}: {temp}°C, {condition}"
                    }]
                }
            }
            
            print(json.dumps(response), flush=True)
            
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
'''

STOCK_MCP_CODE = '''
"""
Simulated Stock MCP Server  
Responds with stock prices
"""
import sys, json, time, random

print("📈 Stock MCP Server started", file=sys.stderr)

stock_prices = {
    "AAPL": 182.63,
    "TSLA": 175.79,
    "MSFT": 407.81,
    "GOOGL": 148.32
}

while True:
    try:
        line = sys.stdin.readline()
        if not line:
            break
        
        request = json.loads(line)
        
        if request["method"] == "tools/call":
            symbol = request["params"]["arguments"]["symbol"]
            
            # Simulate API delay
            delay = random.uniform(0.2, 0.8)
            time.sleep(delay)
            
            # Get price with small random variation
            base_price = stock_prices.get(symbol, 100.0)
            variation = random.uniform(-2.0, 2.0)
            price = round(base_price + variation, 2)
            
            response = {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": {
                    "content": [{
                        "type": "text",
                        "text": f"{symbol}: ${price}"
                    }]
                }
            }
            
            print(json.dumps(response), flush=True)
            
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
'''


def create_mcp_server_files():
    """Create simulated MCP server files for testing"""
    with open("weather_mcp.py", "w") as f:
        f.write(WEATHER_MCP_CODE)

    with open("stock_mcp.py", "w") as f:
        f.write(STOCK_MCP_CODE)

    print("📁 Created MCP server files")


# ========== MAIN DEMONSTRATION ==========


def main():
    """Main demonstration function"""
    print("=" * 60)
    print("AI APP WITH MCP SERVERS - COMPLETE DEMONSTRATION")
    print("=" * 60)

    # Create MCP server files
    create_mcp_server_files()

    # Create AI agent
    agent = MyAIAgent()

    # Start MCP servers (starts subprocesses and listener threads)
    agent.start_mcp_servers()

    print("\n" + "=" * 60)
    print("DEMONSTRATION: Concurrent Requests with Callbacks")
    print("=" * 60)

    # Give servers time to start
    time.sleep(0.5)

    # 🔥 Key demonstration: Make concurrent requests
    print("\n1️⃣  Making CONCURRENT requests (main thread doesn't block):")
    print("   Main thread continues immediately after each call!")

    agent.ask_question("Beijing weather")
    print("   Main: Immediately continued after Beijing request")

    agent.ask_question("Shanghai weather")
    print("   Main: Immediately continued after Shanghai request")

    agent.ask_question("Apple stock price")
    print("   Main: Immediately continued after Apple request")

    agent.ask_question("Tesla stock price")
    print("   Main: Immediately continued after Tesla request")

    print("\n📊 Main thread free to handle user input while waiting for responses...")

    # Wait for all callbacks to complete
    print("\n⏳ Waiting for responses (callbacks execute in listener threads)...")
    time.sleep(3)

    # Show what happened
    print("\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)

    print(f"\n📋 Results in queue: {len(agent.results_queue)} items")
    for result in agent.results_queue:
        print(f"   • {result}")

    # Check for pending requests
    with agent.lock:
        if agent.pending_requests:
            print(f"\n⚠️  {len(agent.pending_requests)} requests still pending")
        else:
            print("\n✅ All requests completed successfully!")

    # Cleanup
    agent.cleanup()

    print("\n" + "=" * 60)
    print("DEMONSTRATION COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
