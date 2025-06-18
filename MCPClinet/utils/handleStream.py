import json
from collections import defaultdict
from typing import List, Dict, Tuple, Union
import requests
def parse_stream_response(
    stream_data: List[Dict]
) -> Tuple[str, List[Dict[str, Union[str, Dict]]]]:
    """
    解析 OpenAI 流式响应，提取自然语言回复与工具调用信息。

    参数：
        stream_data (List[Dict]): OpenAI 流式响应组成的列表。

    返回：
        Tuple[str, List[Dict]]: (自然语言回复, 工具调用信息列表)
            - response_text (str): 拼接后的自然语言回复
            - tool_calls_info (List[Dict]): 工具调用信息，每个字典包含函数名和参数
    """
    content_parts = []
    tool_calls = defaultdict(lambda: {"function": {"name": "", "arguments": ""}})

    for part in stream_data:
       
        delta = part['choices'][0].get("delta", {})

        # 收集 assistant 的自然语言输出
        if "content" in delta and isinstance(delta["content"], str):
            content_parts.append(delta["content"])

        # 收集工具调用内容
        if "tool_calls" in delta:
            for tool_call in delta["tool_calls"]:
                index = tool_call.get("index")
                if index is None:
                    continue

                if index not in tool_calls:
                    tool_calls[index] = {
                        "id": "",
                        "type": tool_call.get("type", "function"),
                        "function": {
                            "name": "",
                            "arguments": ""
                        }
                    }

                # 合并 tool_call id
                call_id = tool_call.get("id")
                if isinstance(call_id, str) and call_id:
                    tool_calls[index]["id"] = call_id

                # 合并 function name 和 arguments
                func = tool_call.get("function", {})
                if "name" in func and isinstance(func["name"], str):
                    tool_calls[index]["function"]["name"] += func["name"]
                if "arguments" in func and isinstance(func["arguments"], str):
                    tool_calls[index]["function"]["arguments"] += func["arguments"]
    # 拼接自然语言内容
    response_text = ''.join(content_parts)

    # 构建工具调用信息列表
    tool_calls_info = []
    for index in sorted(tool_calls.keys()):
        func_info = tool_calls[index]["function"]
        try:
            args = json.loads(func_info["arguments"])
        except json.JSONDecodeError:
            args = func_info["arguments"]
        tool_calls_info.append({
            "tool_call_id":tool_calls[index]["id"],
            "tool_name": func_info["name"],
            "tool_args": args
        })

    origin_tools =convert_tools_to_json(tool_calls)
    return response_text, tool_calls_info,origin_tools['tool_calls']



def get_stream_chunks(response: requests.Response):
    """
    从 OpenAI 流式响应中提取有效 JSON 块，过滤掉非 data 开头的行和 '[DONE]'
    """
    chunks = []
    for line in response.iter_lines(decode_unicode=True):
        if line and line.startswith("data: "):
            data = line[len("data: "):].strip()
            if data != "[DONE]":
                try:
                    chunks.append(json.loads(data))
                except json.JSONDecodeError:
                    print(f"无法解析 JSON: {data}")
    return chunks




def convert_tools_to_json(origin_tools):
    
    tool_calls = {

        "tool_calls": [
            {
                "id": tool['id'],
                "function": tool['function'],
                "type": tool['type'],
                "index": idx
            }
            for idx, tool in origin_tools.items()
        ]
    }

   
    return tool_calls



from collections import defaultdict
from typing import List, Dict, Tuple, Union
import json

async def parse_stream_response_websocket(websocket, stream_iterator, is_new_reasoning_phase: bool = True):
    """
    解析 OpenAI 流式响应，提取自然语言回复与工具调用信息，同时实时推送内容到前端。
    
    参数：
        websocket: WebSocket 对象，用于向前端推送消息。
        stream_iterator: 异步生成器，提供流式数据。
        is_new_reasoning_phase (bool): 指示当前处理的流是否为一个新的主要思考阶段的开始。
                                     例如，对用户新查询的初步思考，或在工具调用返回结果后的再次思考。
                                     默认为 True。
                                     
    返回：
        Tuple[str, List[Dict], List[Dict]]: 
            - response_text: 拼接后的自然语言回复
            - tool_calls_info: 格式化后的工具调用信息列表
            - origin_tools: 原始工具调用数据列表（结构化）
    """
    content_parts = []
    # 使用 tool_calls_data 存储原始工具调用数据，避免与Python内置的 tool_calls 冲突 (如果存在)
    tool_calls_data = defaultdict(lambda: {
        "id": "",
        "type": "function", # 默认类型
        "function": {"name": "", "arguments": ""}
    })
    
    # 标记是否已经在此次函数调用（代表一个思考阶段）中发送了第一个推理步骤
    # `is_new_reasoning_phase` 由调用者传入，表示这是一个宏观的新阶段
    # `sent_first_reasoning_chunk_in_this_phase` 用于确保只在该阶段的第一个推理信息块上标记 newStep=true
    sent_first_reasoning_chunk_in_this_phase = False

    async for chunk in stream_iterator:
        try:
            text = chunk.decode('utf-8')
            # print(f"Raw chunk text: {text}") # 用于调试
            for line in text.split('\n'):
                if line.startswith('data: ') and not line.startswith('data: [DONE]'):
                    json_str = line[6:]
                    try:
                        part = json.loads(json_str)
                        # print(f"Parsed part: {part}") # 用于调试
                        
                        delta = part['choices'][0].get("delta", {})
                        
                        # --- 处理 reasoning_content ---
                        if "reasoning_content" in delta and isinstance(delta["reasoning_content"], str) and delta["reasoning_content"].strip():
                            send_as_new_step = False
                            if is_new_reasoning_phase and not sent_first_reasoning_chunk_in_this_phase:
                                send_as_new_step = True
                                sent_first_reasoning_chunk_in_this_phase = True # 标记已发送此阶段的第一个块
                            
                            await websocket.send(json.dumps({
                                "type": "reasoning",
                                "content": delta["reasoning_content"],
                                "newStep": send_as_new_step # 向前端传递 newStep 标记
                            }))
                        
                        # --- 处理自然语言内容 ---
                        if "content" in delta and isinstance(delta["content"], str) and delta["content"].strip():
                            content_parts.append(delta["content"])
                            await websocket.send(json.dumps({
                                "type": "content",
                                "content": delta["content"]
                                # "newStep" 通常不用于最终内容块，主要用于 reasoning
                            }))
                        
                        # --- 收集工具调用内容 ---
                        if "tool_calls" in delta:
                            # 如果在工具调用信息出现之前已经有思考内容，那么这个思考内容属于上一个步骤。
                            # 工具调用本身，以及之后的思考，将构成新的步骤（由调用者通过新的 is_new_reasoning_phase=True 来发起）
                            for tool_call_delta in delta["tool_calls"]:
                                index = tool_call_delta.get("index")
                                if index is None: # 对于OpenAI的格式，index 应该是存在的
                                    # logger.warning("Tool call delta missing index.")
                                    print("Tool call delta missing index.")
                                    continue
                                
                                # 确保 tool_calls_data[index] 被正确初始化 (defaultdict 会处理)
                                # 更新 ID (通常只在第一个 delta 中出现)
                                if "id" in tool_call_delta and tool_call_delta["id"]:
                                    tool_calls_data[index]["id"] = tool_call_delta["id"]
                                
                                # 更新类型 (通常也只在第一个 delta 中出现)
                                if "type" in tool_call_delta and tool_call_delta["type"]:
                                     tool_calls_data[index]["type"] = tool_call_delta["type"]

                                func_delta = tool_call_delta.get("function", {})
                                if "name" in func_delta and isinstance(func_delta["name"], str):
                                    tool_calls_data[index]["function"]["name"] += func_delta["name"]
                                if "arguments" in func_delta and isinstance(func_delta["arguments"], str):
                                    tool_calls_data[index]["function"]["arguments"] += func_delta["arguments"]
                                    
                    except json.JSONDecodeError:
                        # logger.warning(f"Invalid JSON in stream line: {json_str}")
                        print(f"Invalid JSON in stream line: {json_str}")
                        pass # 忽略无效的 JSON 数据
        except Exception as e:
            # logger.error(f"Error processing stream chunk: {e}", exc_info=True)
            print(f"解析流数据时出错: {e}")
    
    response_text = ''.join(content_parts)
    
    tool_calls_info_list = []
    for index in sorted(tool_calls_data.keys()):
        # 确保在流结束后，数据是完整的
        tool_info = tool_calls_data[index]
        func_info = tool_info["function"]

        if not tool_info.get("id") or not func_info.get("name"):
            # logger.warning(f"Incomplete tool call data at index {index}: {tool_info}")
            print(f"Incomplete tool call data at index {index}: {tool_info}")
            continue # 跳过不完整的工具调用信息

        try:
            args = json.loads(func_info["arguments"])
        except json.JSONDecodeError:
            args = func_info["arguments"] # 如果参数不是合法的JSON，则按原样传递
            # logger.warning(f"Tool call arguments for '{func_info['name']}' are not valid JSON: {args}")
            print(f"Tool call arguments for '{func_info['name']}' are not valid JSON: {args}")

        tool_calls_info_list.append({
            "tool_call_id": tool_info["id"],
            "tool_name": func_info["name"],
            "tool_args": args
        })
    
    # origin_tools 应该是包含完整工具调用对象的列表
    origin_tools_list = [tool_calls_data[key] for key in sorted(tool_calls_data.keys()) if tool_calls_data[key].get("id")]
    
    return response_text, tool_calls_info_list, origin_tools_list
