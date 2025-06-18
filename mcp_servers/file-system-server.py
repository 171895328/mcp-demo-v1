import os
import json
from mcp.server import FastMCP

mcp = FastMCP("FileSystemServer")

@mcp.tool()
async def list_files(path: str, recursive: bool = False) -> str:
    """列出指定目录下的所有文件和目录
    
    Args:
        path: 要列出的目录路径
        recursive: 是否递归列出子目录。请牢记：除非用户明确要求，否则禁止递归
        
    Returns:
        JSON格式的文件和目录列表，包含类型信息
    """
    try:
        if not os.path.exists(path):
            return json.dumps({"error": f"Path does not exist: {path}"})
            
        if not os.path.isdir(path):
            return json.dumps({"error": f"Path is not a directory: {path}"})
            
        # 检查目录访问权限
        if not os.access(path, os.R_OK):
            return json.dumps({"error": f"Permission denied: {path}"})
            
        files = []
        if recursive:
            for root, dirs, filenames in os.walk(path):
                # 添加目录
                for dirname in dirs:
                    full_path = os.path.join(root, dirname)
                    files.append({
                        "path": full_path,
                        "type": "directory"
                    })
                # 添加文件
                for filename in filenames:
                    full_path = os.path.join(root, filename)
                    files.append({
                        "path": full_path,
                        "type": "file"
                    })
        else:
            for f in os.listdir(path):
                full_path = os.path.join(path, f)
                try:
                    if os.path.isfile(full_path):
                        files.append({
                            "path": full_path,
                            "type": "file"
                        })
                    elif os.path.isdir(full_path):
                        files.append({
                            "path": full_path,
                            "type": "directory"
                        })
                except PermissionError:
                    # 记录权限错误
                    print(f"Permission denied: {full_path}")
                    continue
                except Exception as e:
                    # 记录其他错误
                    print(f"Error accessing {full_path}: {str(e)}")
                    continue
            
        return json.dumps(files, ensure_ascii=False, indent=2)
        
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool()
async def read_file(path: str) -> str:
    """读取指定文件的内容
    
    Args:
        path: 要读取的文件路径
        
    Returns:
        文件内容字符串
    """
    try:
        if not os.path.exists(path):
            return json.dumps({"error": f"File does not exist: {path}"})
            
        if not os.path.isfile(path):
            return json.dumps({"error": f"Path is not a file: {path}"})
            
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
            
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool()
async def write_file(path: str, content: str) -> str:
    """写入内容到指定文件
    
    Args:
        path: 要写入的文件路径
        content: 要写入的内容,必须为字符串
        
    Returns:
        操作结果（成功或错误信息）
    """
    try:
        # 检查路径合法性
        if not path or any(c in path for c in '<>"|?*'):
            return json.dumps({"error": f"Invalid path: {path}"})
            
        # 检查父目录是否存在，不存在则创建
        dir_path = os.path.dirname(path)
        if dir_path and not os.path.exists(dir_path):
            try:
                os.makedirs(dir_path)
            except Exception as e:
                return json.dumps({"error": f"Failed to create parent directory: {str(e)}"})
                
        # 检查是否有写权限
        if os.path.exists(path) and not os.access(path, os.W_OK):
            return json.dumps({"error": f"No write permission: {path}"})
            
        # 检查磁盘空间
        if not os.path.exists(path):
            try:
                stat = os.statvfs(dir_path)
                if stat.f_bavail * stat.f_frsize < len(content):
                    return json.dumps({"error": "Insufficient disk space"})
            except Exception:
                pass
                
        # 写入文件
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            return json.dumps({"success": True})
        except UnicodeEncodeError:
            try:
                with open(path, 'w', encoding='utf-16') as f:
                    f.write(content)
                return json.dumps({"success": True})
            except Exception as e:
                return json.dumps({"error": f"Encoding error: {str(e)}"})
                
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool()
async def create_directory(path: str) -> str:
    """创建目录
    
    Args:
        path: 要创建的目录路径
        
    Returns:
        操作结果（成功或错误信息）
    """
    try:
        # 检查路径是否已存在
        if os.path.exists(path):
            return json.dumps({"error": f"Path already exists: {path}"})
            
        # 检查父目录是否存在
        parent_dir = os.path.dirname(path)
        if parent_dir and not os.path.exists(parent_dir):
            return json.dumps({"error": f"Parent directory does not exist: {parent_dir}"})
            
        # 检查是否有写权限
        if not os.access(parent_dir, os.W_OK):
            return json.dumps({"error": f"No write permission: {parent_dir}"})
            
        # 创建目录
        os.makedirs(path)
        return json.dumps({"success": True})
        
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool()
async def create_file(path: str) -> str:
    """创建空文件
    
    Args:
        path: 要创建的文件路径
        
    Returns:
        操作结果（成功或错误信息）
    """
    try:
        # 检查文件是否已存在
        if os.path.exists(path):
            return json.dumps({"error": f"File already exists: {path}"})
            
        # 检查父目录是否存在
        parent_dir = os.path.dirname(path)
        if parent_dir and not os.path.exists(parent_dir):
            return json.dumps({"error": f"Parent directory does not exist: {parent_dir}"})
            
        # 检查是否有写权限
        if not os.access(parent_dir, os.W_OK):
            return json.dumps({"error": f"No write permission: {parent_dir}"})
            
        # 创建空文件
        open(path, 'a').close()
        return json.dumps({"success": True})
        
    except Exception as e:
        return json.dumps({"error": str(e)})

if __name__ == "__main__":
    mcp.run(transport="stdio")
