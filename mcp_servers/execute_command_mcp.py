import subprocess
import asyncio # 确保导入 asyncio
from mcp.server import FastMCP

mcp = FastMCP("ExecuteCommandServer")

@mcp.tool()
async def execute_command_tool(command: str, requires_approval: bool = False, env: str = "mcp") -> str:
    """执行指定的CLI命令

    Args:
        command: 要执行的CLI命令
        requires_approval: 是否需要用户批准（默认为False）
        env: 命令执行的环境（默认为'mcp' conda环境）

    Returns:
        命令执行结果的字符串
    """
    if requires_approval:
        return "Error: Command requires approval"

    try:
        # 推荐的方式
        if env and env.lower() != "base": # 'base' 环境通常不需要特殊激活
            full_command = f"conda run -n {env} {command}"
        else:
            full_command = command # 直接执行命令，可能在 base 或无 conda 环境

        # 或者，如果希望即使是 base 环境也通过 conda run (虽然通常没必要)
        # full_command = f"conda run -n {env} {command}"

        # 使用 asyncio.to_thread 运行阻塞代码
        process_result = await asyncio.to_thread(
            subprocess.run,
            full_command,
            shell=True,
            capture_output=True,
            text=True,
            check=False # check=False 允许我们手动检查 returncode
        )

        if process_result.returncode == 0:
            return process_result.stdout
        else:
            return f"Error: {process_result.stderr}"
    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == "__main__":
    mcp.run(transport="stdio")