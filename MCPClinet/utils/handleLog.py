from tabulate import tabulate
import datetime
import json
def log_llm_summary(response: dict):
    def ns_to_ms(ns):
        return round(ns / 1_000_000, 2)

    # 只提取并显示所需数据
    table_data = [
        ["模型名称", response.get('model')],
        ["响应时间", response.get('created_at')],
        ["总耗时", f"{ns_to_ms(response['total_duration'])} ms"],
        ["加载耗时", f"{ns_to_ms(response['load_duration'])} ms"],
        ["Prompt tokens", f"{response['prompt_eval_count']} 个, 耗时: {ns_to_ms(response['prompt_eval_duration'])} ms"],
        ["生成 tokens", f"{response['eval_count']} 个, 耗时: {ns_to_ms(response['eval_duration'])} ms"]
    ]

    print("\n=== 🧠 模型调用日志 ===")
    print(tabulate(table_data, headers=["字段", "值"], tablefmt="grid"))
    print("=" * 40 + "\n")
    
    
def log_tool_info(tool_name,tool_args,tool_content):
    
    with open("log/tool_output.log", "a", encoding="utf-8") as f:
        f.write(f"[{datetime.datetime.now()}],工具名:{tool_name},工具参数:{tool_args},执行结果: {tool_content}\n\n")   
    summary = (tool_content[:10] + '...') if len(tool_content) > 10 else tool_content
    print(f"工具执行结果为: {summary}（完整结果已记录到日志）")
    print()
    
    
    
async def log_tool_info_websocket(tool_name, tool_args, tool_content, websocket):
    # 1. 写入日志文件
    with open("log/tool_output.log", "a", encoding="utf-8") as f:
        f.write(
            f"[{datetime.datetime.now()}],工具名:{tool_name},工具参数:{tool_args},执行结果: {tool_content}\n\n"
        )

    # 2. 简要信息（用于控制台和 WebSocket）
    summary = (tool_content[:50] + '...') if len(tool_content) > 50 else tool_content
    print(f"工具执行结果为: {summary}（完整结果已记录到日志）\n")

    # 3. WebSocket 推送
    await websocket.send(json.dumps({
        "type": "tool_result",
        "tool_name": tool_name,
        "tool_args": tool_args,
        "tool_result": summary
    }))
    
def outputTokenInfo(response):
    response_json = response.json()  # 使用json()方法直接获取JSON数据
    
    # 获取usage部分的信息
    usage = response_json.get("usage", {})
    pt = usage.get('prompt_tokens')
    ct = usage.get('completion_tokens')
    tt = usage.get('total_tokens')
    cache = usage.get('prompt_tokens_details', {}).get('cached_tokens')
    print(f"[Token]  total: {tt}, prompt: {pt}, completion: {ct}, cached: {cache}")