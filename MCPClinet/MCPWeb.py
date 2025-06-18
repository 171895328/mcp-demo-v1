import asyncio
import json
import os
import traceback
import re
from typing import Dict, List, Any, Optional
from contextlib import AsyncExitStack
# import requests # 不再使用 requests
import httpx # <--- 引入 httpx
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
from utils.TokenAndConversation import TokenCounter, ConversationManager
from utils.handleLog import log_tool_info_websocket, outputTokenInfo 
from utils.handleStream import parse_stream_response_websocket, get_stream_chunks
from quart import Quart, websocket, current_app
import traceback

# --- 配置区 ---
load_dotenv('../Aliyunmodel.env')
isStream = True # 是否启用流式输出
MAX_TOOL_ITERATIONS = 5 # 最大工具调用迭代次数
LLM_TIMEOUT = 180 # LLM 调用超时 (秒)
TOOL_TIMEOUT = 120 # 工具调用超时 (秒)

STDIO_MCP_CONFIG = "../MCPConfig/stdio_mcp_config.json"
SSE_MCP_CONFIG = "../MCPConfig/sse_mcp_config.json"

# --- 全局 App 和 MCP 客户端 ---
app = Quart(__name__)
mcp_client: Optional['MCPClient'] = None # 全局客户端实例

# --- Helper 函数 ---
async def safe_send_json(ws, data: Dict[str, Any]):
    """安全地发送 JSON 格式的消息到 WebSocket"""
    try:
        await ws.send(json.dumps(data))
    except Exception as e:
        print(f"发送 WebSocket 消息失败: {str(e)}")
        traceback.print_exc()

async def send_error_to_websocket(ws, error_message: str, details: str = ""):
    """向 WebSocket 发送结构化的错误消息"""
    await safe_send_json(ws, {
        "type": "error",
        "message": error_message,
        "details": details
    })

async def send_content_to_websocket(ws, content: str):
    """向 WebSocket 发送 AI 内容消息"""
    await safe_send_json(ws, {"type": "content", "content": content})

async def send_system_message_to_websocket(ws, message: str):
    """向 WebSocket 发送系统消息"""
    
    
    if isinstance(message, bytes):
        message = message.decode('utf-8')
    
    
    await safe_send_json(ws, {"type": "system", "content": message})

# --- 类定义 (基本保持不变，除了 LLMClient 和 WebSocket 相关部分) ---

class MCPClientConfig:
    """处理MCP客户端配置的类"""
    def __init__(self):
        self.model = os.getenv('MODEL')
        self.model_base_url = os.getenv('MODEL_BASE_URL')
        self.model_api_key = os.getenv('MODEL_API_KEY')
        self.model_contextWindow = int(os.getenv('MODEL_API_OPTION_CONTEXTWINDOWS', 16000)) # 提供默认值并转为 int

        self.is_aliyun = self.model_base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

        if self.is_aliyun:
            print("————————————————————————————当前使用阿里云百炼API——————————————————————————")
        else:
            print("————————————————————————————当前使用硅基流动API——————————————————————————")

        self.stdio_server_config = self._load_server_config(STDIO_MCP_CONFIG)
        self.sse_server_config = self._load_server_config(SSE_MCP_CONFIG)

    def _load_server_config(self, mcp_config: str, server_name=None):
        try:
            with open(mcp_config, 'r', encoding='utf-8') as f:
                config = json.load(f)
            if server_name:
                return config["servers"].get(server_name)
            return config
        except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
            print(f"加载配置文件 {mcp_config} 出错: {str(e)}")
            return {}

class ToolAdapter:
    """工具格式转换和管理"""
    @staticmethod
    def convert_tool_format(tool):
        """将MCP工具格式转换为LLM工具调用格式"""
        properties = {}
        for name, prop in tool.inputSchema.get("properties", {}).items():
            prop_type = prop.get("type", "string")
            description = prop.get("description", "")
            if isinstance(prop_type, list):
                main_type = prop_type[0] if prop_type else "string"
                description += f" (支持的类型: {', '.join(prop_type)})"
                properties[name] = {"type": main_type, "description": description}
            else:
                properties[name] = {"type": prop_type, "description": description}

        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": tool.inputSchema.get("required", [])
                }
            }
        }

    @staticmethod
    def parse_tool_calls(content: Dict) -> List[Dict]:
        """解析AI返回的工具调用 (兼容流式和非流式)"""
        # print(f"DEBUG: Parsing tool calls from content: {content}") # Debugging
        tool_calls_list = []

        # 优先处理标准 'tool_calls' 字段
        raw_tool_calls = content.get("tool_calls")
        if raw_tool_calls and isinstance(raw_tool_calls, list):
            for tool_call in raw_tool_calls:
                try:
                    function_info = tool_call.get("function", {})
                    tool_name = function_info.get("name")
                    tool_args_raw = function_info.get("arguments")
                    tool_call_id = tool_call.get("id")

                    if not tool_name or not tool_call_id:
                        print(f"警告: 忽略无效的工具调用数据: {tool_call}")
                        continue

                    tool_args = {}
                    if isinstance(tool_args_raw, dict):
                        tool_args = tool_args_raw
                    elif isinstance(tool_args_raw, str) and tool_args_raw.strip():
                        try:
                            tool_args = json.loads(tool_args_raw)
                        except json.JSONDecodeError:
                            print(f"警告: 工具 {tool_name} 的参数无法解析为 JSON: {tool_args_raw}")
                            # 可以选择将原始字符串作为参数，或置空
                            tool_args = {"raw_arguments": tool_args_raw} # 或者 {}
                    elif tool_args_raw is None:
                         tool_args = {} # 允许空参数

                    tool_calls_list.append({
                        "tool_name": tool_name,
                        "tool_args": tool_args,
                        "tool_call_id": tool_call_id
                    })
                except Exception as e:
                    print(f"解析标准 tool_calls 时出错: {e}, tool_call data: {tool_call}")
                    traceback.print_exc()
            return tool_calls_list # 如果有标准 tool_calls 就直接返回

        # 兼容处理 'reasoning_content' (如果标准字段不存在)
        # 注意：这种解析方式比较脆弱，依赖特定格式
        reasoning = content.get("reasoning_content", "")
        if reasoning and "</tool_call>" in reasoning:
             print("警告: 未找到标准 'tool_calls'，尝试从 'reasoning_content' 解析")
             try:
                 # 正则表达式尝试提取 JSON 对象
                 # 这个正则可能需要根据实际的 reasoning_content 格式调整
                 match = re.search(r'<tool_call>.*?(\{.*?\})', reasoning, re.DOTALL)
                 if match:
                     tool_call_json_str = match.group(1)
                     tool_call_data = json.loads(tool_call_json_str)
                     if "name" in tool_call_data and "id" in tool_call_data:
                         tool_calls_list.append({
                             "tool_name": tool_call_data["name"],
                             "tool_args": tool_call_data.get("arguments", {}),
                             "tool_call_id": tool_call_data["id"]
                         })
                         print(f"DEBUG: Parsed from reasoning: {tool_calls_list}")
             except Exception as e:
                 print(f"从 reasoning_content 解析工具调用失败: {e}")
                 traceback.print_exc()

        return tool_calls_list


class LLMClient:
    """处理与LLM API的通信 (使用 httpx)"""
    def __init__(self, config: MCPClientConfig):
        self.config = config
        # 创建可复用的 httpx 客户端
        self.http_client = httpx.AsyncClient(timeout=LLM_TIMEOUT) # 设置超时

    async def call_llm(self, websocket, messages: List[Dict], tools: List = None) -> Dict:
        """调用LLM API获取响应 (使用 httpx)"""
        data = {
            "model": self.config.model,
            "messages": messages,
            "stream": isStream
        }
        if tools:
            data["tools"] = tools
            # 根据需要添加特定模型的参数
            if self.config.is_aliyun:
                data["parallel_tool_calls"] = True # 阿里云特定参数
                data["result_format"] = "message" # 阿里云推荐使用 message 格式
            else:
                # 可能需要为其他模型添加 tool_choice 等参数
                data["tool_choice"] = "auto"

        headers = {
            "Authorization": f"Bearer {self.config.model_api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if isStream else "application/json" # 明确 Accept 类型
        }

        # print(f"--- LLM Request Data ---")
        # print(json.dumps(data, indent=2, ensure_ascii=False))
        # print(f"--- Headers ---")
        # print(headers)
        # print(f"--- URL ---")
        # print(self.config.model_base_url)
        # print(f"------------------------")


        try:
            async with self.http_client.stream("POST", self.config.model_base_url, json=data, headers=headers) if isStream \
                 else self.http_client.post(self.config.model_base_url, json=data, headers=headers) as response:

                # print(f"LLM Response Status Code: {response.status_code}") # Debugging

                if response.status_code != 200:
                    error_content = await response.aread() # 读取错误响应体
                    print(f"LLM 请求失败，状态码: {response.status_code}, 响应: {error_content.decode()}")
                    await send_error_to_websocket(websocket, f"LLM 请求失败", f"状态码: {response.status_code}, 响应: {error_content.decode()}")
                    return {"error": f"LLM 请求失败，状态码: {response.status_code}"}
                print("response",response)
                if isStream:
                    # 处理流式响应 
                    async def stream_iterator():
                        async for chunk in response.aiter_bytes():
                            yield chunk

                    response_text, tool_calls_info, origin_tools = await parse_stream_response_websocket(websocket, stream_iterator())
                    # 流式响应解析后，需要组装成与非流式兼容的格式
                    response_data = {
                        "choices": [{
                             "message": {
                                 "role": "assistant",
                                 "content": response_text if not tool_calls_info else None, # 如果有工具调用，内容通常为 None
                                 "tool_calls": origin_tools if tool_calls_info else None
                             },
                             "finish_reason": "tool_calls" if tool_calls_info else "stop" # 模拟 finish_reason
                        }]
                        # 可能还需要 usage 信息，但流式通常不直接提供最终 token 数
                    }
                    # print(f"DEBUG: Assembled Stream Response Data: {response_data}") # Debugging
                    return response_data
                else:
                    # 处理非流式响应
                    response_data = await response.json()
                    # print(f"DEBUG: Non-Stream Response Data: {response_data}") # Debugging
                    # outputTokenInfo(response_data) # 非流式可以获取 token 信息
                    if not response_data:
                        print("API响应内容为空")
                        await send_error_to_websocket(websocket, "API 响应为空")
                        return {"error": "API响应内容为空"}
                    return response_data

        except httpx.RequestError as e:
            print(f"LLM 请求网络错误: {e}")
            traceback.print_exc()
            await send_error_to_websocket(websocket, "LLM 请求网络错误", str(e))
            return {"error": f"LLM 请求网络错误: {e}"}
        except json.JSONDecodeError as e:
            print(f"解析 LLM 响应 JSON 失败: {e}")
            traceback.print_exc()
            await send_error_to_websocket(websocket, "解析 LLM 响应失败", str(e))
            return {"error": f"解析 LLM 响应 JSON 失败: {e}"}
        except Exception as e:
            print(f"调用 LLM 时发生未知错误: {e}")
            traceback.print_exc()
            await send_error_to_websocket(websocket, "调用 LLM 时发生未知错误", str(e))
            return {"error": f"调用 LLM 时发生未知错误: {e}"}

    async def close(self):
        """关闭 httpx 客户端"""
        await self.http_client.aclose()


class MCPClient:
    """MCP客户端主类"""
    def __init__(self) -> None:
        self.config = MCPClientConfig()
        self.llm_client = LLMClient(self.config)
        self.exit_stack = AsyncExitStack()
        self.sessions: Dict[str, ClientSession] = {} # 添加类型提示
        self.connected_servers: set[str] = set() # 添加类型提示

        # ConversationManager 需要根据会话 ID 管理，这里暂时还是全局
        # **警告: 这是单用户模式，多用户需要改造**
        self.token_counter = TokenCounter()
        self.conversation_manager = ConversationManager(
            model_api_url=self.config.model_base_url,
            model_name=self.config.model,
            token_counter=self.token_counter,
        
        )
        self.conversation_manager.add_message(
            {
                "role":"system",
                "content":"请从记忆(当前使用memory服务器的知识图谱保存记忆)中读取记忆"
                
            }
        )
        self.max_tool_iterations = MAX_TOOL_ITERATIONS

    async def connect_to_servers(self) -> None:
        """连接到所有配置的MCP服务器（支持幂等）"""
        # --- 连接 STDIO 服务器 ---
        for server_name, server_config in self.config.stdio_server_config.get("servers", {}).items():
            if server_name in self.connected_servers: continue
            try:
                server_params = StdioServerParameters(**server_config)
                stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
                stdio, write = stdio_transport
                session = await self.exit_stack.enter_async_context(ClientSession(stdio, write))
                await session.initialize()
                self.sessions[server_name] = session
                self.connected_servers.add(server_name)
                print(f"✅ 成功连接到 STDIO 服务器 `{server_name}`")
            except Exception as e:
                print(f"❌ 连接到 STDIO 服务器 {server_name} 失败: {e}")
                traceback.print_exc() # 打印详细错误

        # --- 连接 SSE 服务器 ---
        for server_name, server_config in self.config.sse_server_config.get("servers", {}).items():
            if server_name in self.connected_servers: continue
            try:
                server_url = server_config.get("url")
                if not server_url:
                    print(f"❌ SSE 服务器 {server_name} 配置缺少 'url'")
                    continue
                sse_transport = await self.exit_stack.enter_async_context(sse_client(url=server_url))
                read, write = sse_transport
                session = await self.exit_stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                self.sessions[server_name] = session
                self.connected_servers.add(server_name)
                print(f"✅ 成功连接到 SSE 服务器 `{server_name}`")
            except Exception as e:
                print(f"❌ 连接到 SSE 服务器 {server_name} 失败: {e}")
                traceback.print_exc()

    async def get_available_tools(self) -> List:
        """获取所有服务器上可用的工具，并转换为 LLM 格式"""
        all_tools = []
        for server_name, session in self.sessions.items():
            try:
                response = await session.list_tools()
                for tool in response.tools:
                    original_name = tool.name
                    # 修改工具对象本身的 name 属性
                    tool.name = f"{server_name}.{original_name}"
                    all_tools.append(tool)
            except Exception as e:
                print(f"获取服务器 {server_name} 的工具列表失败: {e}")
                traceback.print_exc()
        return [ToolAdapter.convert_tool_format(tool) for tool in all_tools]

    async def list_resources(self, ws):
        """列出所有可用资源并发送到 WebSocket"""
        resource_list = []
        for server_name, session in self.sessions.items():
            try:
                response = await session.list_resources()
                if response.resources:
                    for resource in response.resources:
                        resource_list.append(f"- {server_name}.{resource.name}: {resource.description}")
                else:
                     resource_list.append(f"服务器 {server_name} 没有可用资源")
            except Exception as e:
                msg = f"获取服务器 {server_name} 的资源列表失败: {str(e)}"
                print(msg)
                resource_list.append(msg)
        await send_system_message_to_websocket(ws, "可用资源列表:\n" + "\n".join(resource_list))

    async def list_prompts(self, ws):
        """列出所有可用提示并发送到 WebSocket"""
        prompt_list_str = []
        for server_name, session in self.sessions.items():
            try:
                response = await session.list_prompts()
                if response.prompts:
                    prompt_list_str.append(f"服务器 {server_name} 的提示:")
                    for prompt in response.prompts:
                        prompt_list_str.append(f"- {server_name}.{prompt.name}: {prompt.description}")
                        if prompt.arguments:
                            prompt_list_str.append("  参数:")
                            for arg in prompt.arguments:
                                required = "（必填）" if getattr(arg, "required", False) else ""
                                prompt_list_str.append(f"    {arg.name}{required}: {arg.description or '无描述'}")
                else:
                    prompt_list_str.append(f"服务器 {server_name} 没有可用提示")
            except Exception as e:
                msg = f"获取服务器 {server_name} 的提示列表失败: {str(e)}"
                print(msg)
                prompt_list_str.append(msg)
        await send_system_message_to_websocket(ws, "可用提示列表:\n" + "\n".join(prompt_list_str))

    async def handle_resource_command(self, args, ws):
        """处理资源命令，并通过 WebSocket 发送结果或错误"""
        if not args or len(args) < 2 or args[0].lower() not in ['get', 'use']:
            await send_error_to_websocket(ws, "命令格式错误", "用法: /resource [get|use] <server_name>.<resource_name>")
            return

        action = args[0].lower()
        resource_full_name = args[1]

        if '.' not in resource_full_name:
            await send_error_to_websocket(ws, "资源名称格式错误", "请使用格式: <server_name>.<resource_name>")
            return

        server_name, actual_resource_name = resource_full_name.split('.', 1)

        if server_name not in self.sessions:
            await send_error_to_websocket(ws, f"未找到服务器: {server_name}")
            return

        try:
            result = await self.sessions[server_name].read_resource(actual_resource_name)
            resource_content = result.contents if result and result.contents else "资源无内容或读取失败"

            if action == 'get':
                await send_system_message_to_websocket(ws, f"资源 {resource_full_name} 内容:\n{resource_content}")
            elif action == 'use':
                self.conversation_manager.add_message({
                    "role": "system",
                    "content": f"以下是资源 {resource_full_name} 的内容:\n{resource_content}"
                }, is_key_message=True)
                await send_system_message_to_websocket(ws, f"已将资源 {resource_full_name} 添加到对话上下文。")

        except Exception as e:
            error_msg = f"处理资源 {resource_full_name} ({action}) 失败: {str(e)}"
            print(error_msg)
            traceback.print_exc()
            await send_error_to_websocket(ws, f"处理资源 {resource_full_name} 失败", str(e))

    async def handle_prompt_command(self, args, ws):
        """处理提示命令，并通过 WebSocket 发送结果或错误"""
        if not args or len(args) < 1:
             await send_error_to_websocket(ws, "命令格式错误", "用法: /prompt <server_name>.<prompt_name> [可选的JSON参数]")
             return

        prompt_full_name = args[0]
        if '.' not in prompt_full_name:
            await send_error_to_websocket(ws, "提示名称格式错误", "请使用格式: <server_name>.<prompt_name>")
            return

        server_name, actual_prompt_name = prompt_full_name.split('.', 1)

        if server_name not in self.sessions:
             await send_error_to_websocket(ws, f"未找到服务器: {server_name}")
             return

        params = {}
        if len(args) > 1:
            try:
                params_str = ' '.join(args[1:])
                params = json.loads(params_str)
            except json.JSONDecodeError:
                 await send_error_to_websocket(ws, "参数格式错误", "请提供有效的 JSON 格式参数。")
                 return

        try:
            result = await self.sessions[server_name].get_prompt(actual_prompt_name, params)
            # get_prompt 返回的是 GetPromptResponse，其 messages 属性是 List[Message]
            # 需要将 Message 对象列表转换为适合添加到 conversation_manager 的字典列表
            prompt_messages = []
            if result and result.messages:
                 for msg in result.messages:
                     # 假设 Message 对象有 role 和 content 属性
                     prompt_messages.append({"role": getattr(msg, 'role', 'system'), "content": getattr(msg, 'content', '')})

            if not prompt_messages:
                 prompt_content_str = "提示执行完成，但未返回消息。"
            else:
                 # 为了添加到上下文，可以将多条消息合并或只取主要内容
                 # 这里简单地将它们 JSON 序列化作为内容
                 prompt_content_str = json.dumps(prompt_messages, ensure_ascii=False, indent=2)


            self.conversation_manager.add_message({
                "role": "system",
                "content": f"执行提示 {prompt_full_name} (参数: {json.dumps(params, ensure_ascii=False)}) 的结果已添加到对话历史。结果内容:\n{prompt_content_str}"
            }, is_key_message=True) # 标记为关键信息

            await send_system_message_to_websocket(ws, f"已执行提示 {prompt_full_name} 并添加结果到对话上下文。")
            # 可以选择发送一个预览，如果结果太长
            # preview = prompt_content_str[:200] + "..." if len(prompt_content_str) > 200 else prompt_content_str
            # await send_system_message_to_websocket(ws, f"结果预览:\n{preview}")

        except Exception as e:
            error_msg = f"执行提示 {prompt_full_name} 失败: {str(e)}"
            print(error_msg)
            traceback.print_exc()
            await send_error_to_websocket(ws, f"执行提示 {prompt_full_name} 失败", str(e))


    async def decide_next_action(self, websocket, query: str = None) -> Dict:
        """决定下一步行动：调用 LLM 获取工具调用或最终响应"""
        if query:
            # 使用ConversationManager添加用户消息
            self.conversation_manager.add_message({"role": "user", "content": query})

            # 移除旧的系统提示，再添加新的 (如果需要动态更新的话)
            self.conversation_manager.diminishByRoleAndKey("system", "关于用户请求的系统提示：") # 假设这个方法有效

            # 添加系统提示 (可以考虑将其移到 ConversationManager 初始化时或作为固定前缀)
            system_prompt = """
                关于用户请求的系统提示：
                请先全面分析用户需求，确定本轮需要调用的所有工具和参数。
                尽可能在同一轮内并发调用所有互不依赖的工具操作，提升性能；如有工具之间的先后依赖，请遵循正确顺序调用。
                在每轮调用前后，都要思考：本轮是否已获取足够信息？工具信息是否返回了错误信息？是否有可并行调用的工具？依赖关系是否已正确处理？

                <你的设定>
         
                </你的设定>

            """
            self.conversation_manager.add_message({"role": "system", "content": system_prompt})

            # 自动优化历史记录
            await self.conversation_manager.optimize_history()

        # 获取可用工具
        available_tools = await self.get_available_tools()

        # 获取当前优化后的消息历史
        current_messages = self.conversation_manager.get_current_messages()

        # 调用 LLM
        response_data = await self.llm_client.call_llm(websocket, current_messages, available_tools)

        if "error" in response_data:
            return response_data # 直接返回错误信息

        # --- 解析 LLM 响应 ---
        try:
            # 非流式和流式现在都返回类似结构
            if not response_data or "choices" not in response_data or not response_data["choices"]:
                 print(f"LLM 响应格式错误或 choices 为空: {response_data}")
                 await send_error_to_websocket(websocket, "LLM 响应格式错误", f"响应: {response_data}")
                 return {"error": "LLM 响应格式错误"}

            assistant_message = response_data["choices"][0].get("message", {})
            finish_reason = response_data["choices"][0].get("finish_reason", "stop")

            # 将助手消息（可能包含工具调用）添加到历史记录
            # 确保即使 content 为 None 也添加，因为可能有 tool_calls
            self.conversation_manager.add_message({
                "role": "assistant",
                "content": assistant_message.get("content"), # 可能为 None
                "tool_calls": assistant_message.get("tool_calls") # 可能为 None
            })

            # 解析工具调用
            # 注意：这里使用解析后的 assistant_message，而不是原始 stream 解析出的 tool_calls_info
            parsed_tool_calls = ToolAdapter.parse_tool_calls(assistant_message)

            # print(f"DEBUG: Parsed tool calls from message: {parsed_tool_calls}") # Debugging

            if parsed_tool_calls and finish_reason == "tool_calls":
                 return {"tool_calls": parsed_tool_calls}
            elif assistant_message.get("content"):
                 # 如果没有工具调用，但有内容，则认为是最终响应
                 # 对于流式，内容在 parse_stream_response_websocket 中已发送，这里不再发送
                 # 对于非流式，内容需要在这里发送
                 if not isStream:
                     await send_content_to_websocket(websocket, assistant_message["content"])
                 return {"response": assistant_message["content"]}
            else:
                 # 既没有工具调用，内容也为空（或 None）
                 print(f"警告: LLM 响应既无内容也无工具调用: {assistant_message}, finish_reason: {finish_reason}")
                 await send_system_message_to_websocket(websocket, "AI 未能生成有效回复或工具调用。")
                 # 可以返回一个空响应或特定错误
                 return {"response": "抱歉，我不知道该如何回应。"}


        except (KeyError, IndexError, TypeError) as e:
            error_msg = f"解析 LLM 响应时出错: {e}"
            print(error_msg)
            print(f"原始响应数据: {response_data}")
            traceback.print_exc()
            await send_error_to_websocket(websocket, "解析 LLM 响应失败", error_msg)
            return {"error": "解析LLM响应失败"}

    async def call_tool_with_timeout(self, session, tool_name, args, timeout=TOOL_TIMEOUT) -> Any:
        """带超时的工具调用，返回 MCP 的原始 Result 对象或错误模拟对象"""
        try:
            # print(f"Calling tool: {tool_name} with args: {args}") # Debugging
            return await asyncio.wait_for(
                session.call_tool(tool_name, args),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            print(f"工具 {tool_name} 调用超时 (>{timeout}s)")
            # 返回一个模拟失败结果的对象，结构类似成功时的 Result
            # 这使得后续处理逻辑可以统一检查 .content
            return type('FakeTimeoutResult', (object,), {"content": [{"text": f"工具 {tool_name} 调用超时"}]})()
        except Exception as e:
            print(f"工具 {tool_name} 调用出错: {str(e)}")
            traceback.print_exc()
            # 返回模拟错误结果的对象
            return type('FakeErrorResult', (object,), {"content": [{"text": f"工具 {tool_name} 调用出错: {str(e)}"}]})()


    async def process_tool_result(self, initial_tool_calls: List[Dict], websocket) -> Optional[str]:
        """处理工具调用（可能多轮），直到获得最终响应或达到迭代上限。返回最终响应字符串或 None (如果出错或无响应)。"""
        pending_calls = initial_tool_calls.copy()
        iteration = 0

        while pending_calls and iteration < self.max_tool_iterations:
            iteration += 1
            print(f"--- 工具调用迭代: {iteration}/{self.max_tool_iterations} ---")

            tool_results_for_llm = [] # 存储本轮发送给 LLM 的工具结果

            # 并发执行本轮所有待处理工具
            tasks = []
            call_details = {} # 存储 task 与 tool_call_id 的映射
            for call in pending_calls:
                 try:
                     tool_name = call["tool_name"]
                     tool_args = call["tool_args"]
                     tool_call_id = call["tool_call_id"]
                     server_name, actual_tool_name = tool_name.split('.', 1)

                     if server_name not in self.sessions:
                         print(f"警告: 工具 {tool_name} 的服务器 {server_name} 未连接，跳过调用。")
                         # 模拟一个错误结果给 LLM
                         tool_results_for_llm.append({
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "content": f"错误: 服务器 '{server_name}' 未连接或不可用。"
                         })
                         continue

                     # 确保参数是字典
                     if not isinstance(tool_args, dict):
                          print(f"警告: 工具 {tool_name} 的参数不是字典: {tool_args}，尝试转换或置空。")
                          if isinstance(tool_args, str):
                              try:
                                  tool_args = json.loads(tool_args) if tool_args.strip() else {}
                              except json.JSONDecodeError:
                                  tool_args = {"raw_argument": tool_args} # 保留原始字符串
                          else:
                              tool_args = {} # 其他类型直接置空

                     task = asyncio.create_task(self.call_tool_with_timeout(
                         self.sessions[server_name],
                         actual_tool_name,
                         tool_args
                     ))
                     tasks.append(task)
                     call_details[task] = {"id": tool_call_id, "name": tool_name, "args": tool_args}

                 except Exception as e:
                     print(f"准备工具调用 {call.get('tool_name', '未知')} 时出错: {e}")
                     traceback.print_exc()
                     # 模拟错误结果
                     tool_results_for_llm.append({
                         "role": "tool",
                         "tool_call_id": call.get("tool_call_id", f"error_{iteration}_{len(tool_results_for_llm)}"),
                         "content": f"错误: 准备工具调用时失败 - {e}"
                     })

            # 等待本轮所有工具调用完成
            completed_tasks = await asyncio.gather(*tasks, return_exceptions=True)

            # 清空待处理列表，准备下一轮（如果需要）
            pending_calls.clear()

            # 处理本轮结果
            for i, result_or_exc in enumerate(completed_tasks):
                 task = tasks[i] # 获取原始 task 对象
                 detail = call_details[task]
                 tool_call_id = detail["id"]
                 tool_name = detail["name"]
                 tool_args = detail["args"]

                 tool_content = "工具调用时发生未知错误" # 默认错误信息
                 if isinstance(result_or_exc, Exception):
                     print(f"工具 {tool_name} 调用 gather 时捕获异常: {result_or_exc}")
                     traceback.print_exc()
                     tool_content = f"工具调用时内部错误: {result_or_exc}"
                 elif result_or_exc is not None:
                     # 检查 call_tool_with_timeout 返回的模拟错误或成功结果
                     if hasattr(result_or_exc, 'content') and result_or_exc.content:
                         print(f"result_or_exc:{result_or_exc}")
                         tool_content = getattr(result_or_exc.content[0], "text", "工具返回了无法解析的内容")
                     else:
                         # 假设是成功但无内容的情况
                         tool_content = "工具执行成功，但未返回任何内容。"
                         # 可以尝试打印 result_or_exc 的类型和内容来调试
                         # print(f"DEBUG: Tool {tool_name} returned unexpected structure: {type(result_or_exc)}, {result_or_exc}")

                 # 发送工具执行信息到 WebSocket
                 await log_tool_info_websocket(tool_name, tool_args, tool_content, websocket) # 假设这个函数存在并发送 JSON

                 # 准备发送给 LLM 的结果格式
                 tool_results_for_llm.append({
                     "role": "tool",
                     "tool_call_id": tool_call_id,
                     "content": str(tool_content) # 确保是字符串
                 })

            # 将本轮所有工具结果添加到历史记录
            for res_msg in tool_results_for_llm:
                 self.conversation_manager.add_message(res_msg, is_key_message=True) # 工具结果通常是关键信息

            # 添加临时系统消息引导决策 (可选，但有助于复杂流程)
            temp_system_msg_content = """
                 请分析最近的用户请求以及所有已调用的工具结果，判断是否已有足够信息完成用户需求。
                 【指引】1. 若足够，请总结生成答复；2. 若不足，请生成下一步工具调用指令；3. 注意错误处理和避免重复调用。
             """
            temp_system_msg = {"role": "system", "content": temp_system_msg_content}
            self.conversation_manager.add_message(temp_system_msg)

            # 优化历史记录
            await self.conversation_manager.optimize_history()

            # 调用 LLM 获取下一步决策
            print("--- 请求 LLM 进行下一步决策 ---")
            # 注意：这里不再传递 query，因为用户原始 query 已在历史中
            decision = await self.decide_next_action(websocket)

            # 移除临时系统消息 (如果添加了)
            self.conversation_manager.messages.remove(temp_system_msg)

            if "error" in decision:
                await send_error_to_websocket(websocket, "处理工具结果时出错", decision['error'])
                return None # 出错，无法继续

            if "tool_calls" in decision:
                 print(f"--- LLM 请求调用新的工具 (迭代 {iteration+1}) ---")
                 pending_calls.extend(decision["tool_calls"])
            elif "response" in decision:
                 print("--- LLM 决定生成最终响应 ---")
                 # 响应已在 decide_next_action 中通过 WebSocket 发送（如果是非流式）
                 # 流式响应也已发送完毕
                 return decision["response"] # 返回最终响应内容
            else:
                 # LLM 既没要求工具调用，也没返回内容
                 print("警告: LLM 在工具调用后未要求新工具也未生成响应。")
                 await send_system_message_to_websocket(websocket, "AI 在处理工具结果后未能确定下一步操作。")
                 return "处理工具结果后未能生成有效回答。"


        # 达到最大迭代次数
        if iteration >= self.max_tool_iterations:
            print(f"警告: 工具调用达到最大迭代次数 ({self.max_tool_iterations})。")
            last_tool_result = []
            for call in pending_calls:
                last_tool_result.append({
                     "role": "tool",
                     "tool_call_id": call['tool_call_id'],
                     "content": 'error:工具调用次数达到上限，工具未执行，请不要再继续生成工具调用而是向用户确认当前状况' # 确保是字符串
                 })
            for res_msg in last_tool_result:
                 self.conversation_manager.add_message(res_msg, is_key_message=True) # 工具结果通常是关键信息
            await send_system_message_to_websocket(websocket, f"工具调用达到最大次数 ({self.max_tool_iterations})，将尝试基于现有信息生成最终回复。")
            # 尝试让 LLM 基于现有信息做最后总结
            final_attempt_decision = await self.decide_next_action(websocket) # 不再传入 query
            if "response" in final_attempt_decision:
                return final_attempt_decision["response"]
            else:
                await send_error_to_websocket(websocket, "达到最大工具调用次数且无法生成最终回复。")
                return "抱歉，处理过程遇到问题，无法完成您的请求。"

        # 理论上不应该执行到这里，除非 initial_tool_calls 为空
        print("警告: process_tool_result 意外结束。")
        return "发生未知错误，无法处理您的请求。"


    async def process_query(self, query: str, websocket) -> Optional[str]:
        """处理用户查询的主方法，返回最终响应字符串或 None"""
        # 第一步：调用 LLM 决定是直接回答还是调用工具
        print(f"--- 处理新查询: {query} ---")
        decision = await self.decide_next_action(websocket, query)

        if "error" in decision:
            # 错误已通过 websocket 发送
            return None
        elif "response" in decision:
             # LLM 直接给出了回答
             # 响应已在 decide_next_action 中发送
             return decision["response"]
        elif "tool_calls" in decision:
             # LLM 要求调用工具
             print("--- 开始处理工具调用流程 ---")
             final_response = await self.process_tool_result(decision["tool_calls"], websocket)
             return final_response # 返回 process_tool_result 的结果 (可能是响应字符串或 None)
        else:
             print("警告: 初始决策既无响应也无工具调用。")
             await send_error_to_websocket(websocket, "无法理解您的请求或生成有效响应。")
             return None

    async def reset_conversation(self):
        """重置对话历史 (全局)"""
        # **警告: 这是全局重置，多用户场景需要修改**
        self.conversation_manager.messages = []
        self.conversation_manager.key_messages = []
        self.conversation_manager.system_summary = None
        print("对话历史已重置 (全局)")

    async def cleanup(self):
        """清理客户端资源"""
        print("正在清理 MCP 客户端资源...")
        try:
            await self.llm_client.close() # 关闭 httpx 客户端
            await self.exit_stack.aclose()
            self.sessions.clear()
            self.connected_servers.clear()
            print("MCP 客户端资源清理完成。")
        except Exception as e:
            print(f"清理资源时出错: {e}")
            traceback.print_exc()

# --- WebSocket Endpoint ---
@app.websocket('/ws')
async def ws():
    global mcp_client
    if mcp_client is None:
        print("错误: MCPClient 未初始化！")
        await websocket.close(code=1011, reason="Server not initialized")
        return

    # **多用户会话管理应该在这里开始**
    # 例如: session_id = request.cookies.get('session_id') or generate_new_id()
    # conversation_mgr = get_or_create_conversation_manager(session_id)
    # 这里我们仍然使用全局的 conversation_manager

    current_conversation = mcp_client.conversation_manager # **指向全局管理器**

    try:
        # 1. 发送连接成功消息
        await send_system_message_to_websocket(websocket._get_current_object(), "连接成功！MCP AI 助手已准备就绪。")
        await send_system_message_to_websocket(websocket._get_current_object(), "输入查询内容, 或使用命令: /reset, /key, /resources, /resource, /prompts, /prompt, /view, /quit")

        """
        # 2. 发送当前历史记录给新连接的前端
        history = current_conversation.get_current_messages() # 获取当前全局历史
        if history:
            await safe_send_json(websocket._get_current_object(), {"type": "history", "data": history})
            print(f"已发送 {len(history)} 条历史记录给新连接。")

        """

        # 3. 进入消息处理循环
        while True:
            try:
                raw_data = await websocket.receive()
                # print(f"Received raw data: {raw_data}") # Debugging

                # 尝试解析为 JSON，如果失败则按普通文本处理
                try:
                    # 如果前端发送的是 JSON 格式 (例如带有 type)
                    data = json.loads(raw_data)
                    query = data.get("content", "").strip() # 假设消息在 content 字段
                    msg_type = data.get("type", "text")
                    if msg_type != "user_input": # 可以定义前端输入类型
                         print(f"收到非用户输入类型的消息: {data}")
                         continue # 或进行其他处理
                except json.JSONDecodeError:
                    # 如果不是 JSON，则认为是普通文本查询
                    query = raw_data.strip()

                if not query:
                    continue

                print(f"收到处理请求: {query}") # 日志记录

                # --- 处理内置命令 ---
                if query.lower() == '/quit':
                    try:
                        await send_system_message_to_websocket(websocket._get_current_object(), "您已断开连接。")
                        print("正在关闭WebSocket连接...")
                        await websocket.close(code=1000, reason="User requested disconnect")
                        print("WebSocket连接已关闭")
                    except Exception as e:
                        print(f"关闭WebSocket连接时出错: {e}")
                        traceback.print_exc()
                    break
                elif query.lower() == '/reset':
                    await mcp_client.reset_conversation() # 重置全局历史
                    await send_system_message_to_websocket(websocket._get_current_object(), "对话已重置。")
                    # 清空前端显示（通过发送空历史或特定命令）
                    await safe_send_json(websocket._get_current_object(), {"type": "history", "data": []})
                    continue
                elif query.lower() == '/key':
                    current_conversation.mark_current_exchange_as_key()
                    await send_system_message_to_websocket(websocket._get_current_object(), "已标记当前交互为关键信息。")
                    continue
                elif query.lower() == '/view':
                    msgs = current_conversation.get_current_messages()
                    history_content = json.dumps(msgs, indent=2, ensure_ascii=False) if msgs else "当前没有对话记录。"
                    # 将历史记录作为系统消息发送，避免前端误认为是 AI 回答
                    await send_system_message_to_websocket(websocket._get_current_object(), f"当前对话上下文:\n```json\n{history_content}\n```")
                    continue
                elif query.startswith('/'):
                     cmd_parts = query[1:].split()
                     cmd = cmd_parts[0].lower()
                     args = cmd_parts[1:]
                     if cmd == 'resources':
                         await mcp_client.list_resources(websocket._get_current_object())
                     elif cmd == 'resource':
                         await mcp_client.handle_resource_command(args, websocket._get_current_object())
                     elif cmd == 'prompts':
                         await mcp_client.list_prompts(websocket._get_current_object())
                     elif cmd == 'prompt':
                         await mcp_client.handle_prompt_command(args, websocket._get_current_object())
                     else:
                         await send_error_to_websocket(websocket._get_current_object(), f"未知命令: {cmd}")
                     continue

                # --- 正常处理用户查询 ---
                # 发送一个 "正在处理" 的消息 (可选)
                # await send_system_message_to_websocket(websocket._get_current_object(), "🤔 正在思考中...")

                # 调用核心处理逻辑
                # 注意：process_query 内部会处理 WebSocket 的响应发送
                await mcp_client.process_query(query, websocket._get_current_object())

                # 可选：在 process_query 返回后发送一个完成标记
                # await send_system_message_to_websocket(websocket._get_current_object(), "✅ 处理完成")


            except asyncio.CancelledError:
                 print("WebSocket 连接被取消。")
                 break # 退出循环
            except Exception as e:
                 # 捕获循环内的其他异常
                 print(f"WebSocket 循环中发生错误: {e}")
                 traceback.print_exc()
                 # 尝试通知客户端错误
                 await send_error_to_websocket(websocket._get_current_object(), "处理您的请求时发生内部错误。", str(e))
                 # 可以选择 break 终止连接，或者 continue 尝试处理下一条消息

    finally:
        # 连接关闭时的清理
        print("WebSocket 连接已关闭。")
        # 如果需要，可以在这里进行特定于此连接的清理
        # 例如: remove_conversation_manager(session_id)


# --- App Lifecycle ---
@app.before_serving
async def startup():
    global mcp_client
    print("服务启动中...")
    mcp_client = MCPClient() # 创建实例
    await mcp_client.connect_to_servers() # 连接 MCP 服务器
    print("MCP 服务器连接完成。服务准备就绪。")

@app.after_serving
async def shutdown():
    global mcp_client
    print("服务关闭，开始清理资源...")
    if mcp_client:
        await mcp_client.cleanup() # 清理 MCP 客户端资源
    print("所有资源清理完成。")

# --- Main Execution ---
if __name__ == "__main__":
    # 注意：生产环境建议使用更健壮的 ASGI 服务器如 Hypercorn 或 Uvicorn
    # 例如: hypercorn your_module:app --bind 127.0.0.1:5000
    app.run(host="127.0.0.1", port=5000,debug=False) # debug 模式建议关闭