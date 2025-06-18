import json
import urllib.parse
import httpx
from mcp.server import FastMCP

mcp = FastMCP("WeatherServer")

OPENWEATHER_API_KEY = "your_openweather_key"
OPENWEATHER_BASE_URL = "https://api.openweathermap.org/data/2.5/weather"
USER_AGENT = "weather-app/1.0"

# 城市名称映射表
CITY_MAPPING = {
    "北京": "Beijing",
    "上海": "Shanghai",
    "广州": "Guangzhou",
    "深圳": "Shenzhen",
    "武汉": "Wuhan",
    "成都": "Chengdu",
    "重庆": "Chongqing",
    "杭州": "Hangzhou",
    "南京": "Nanjing",
    "西安": "Xi'an",
    # 添加更多城市映射...
}

async def get_weather(city):
    # 将中文城市名称转换为英文
    city_name = CITY_MAPPING.get(city, city)
    # 对城市名称进行URL编码
    encoded_city = urllib.parse.quote(city_name)
    
    params = {
        "q": encoded_city,
        "appid": OPENWEATHER_API_KEY,
        "units": "metric",
        "lang": "zh-cn",
    }
    headers = {"User-Agent": USER_AGENT}

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            print(f"正在查询 {city} 的天气信息...")
            response = await client.get(OPENWEATHER_BASE_URL, params=params, headers=headers)
            response.raise_for_status()
            print("天气查询成功")
            return response.json()
        except httpx.HTTPStatusError as e:
            print(f"HTTP 请求失败: {str(e)}")
            return {"error":f"HTTP请求错误:{str(e)}"}
        except httpx.NetworkError as e:
            print(f"网络连接失败: {str(e)}")
            return {"error":f"网络连接失败:{str(e)}"}
        except Exception as e:
            print(f"发生未知错误: {str(e)}")
            return {"error":f"发生未知错误:{str(e)}"}

def format_weather_data(data):
    if isinstance(data, str):
        return json.loads(data)
    if "error" in data:
        return data["error"]
    weather = data["weather"][0]["description"]
    temperature = data["main"]["temp"]
    city = data["name"]
    country = data["sys"]["country"]
    humidity = data["main"]["humidity"]
    wind = data["wind"]["speed"]
    return f"城市:{city},{country}\n天气:{weather}\n温度:{temperature}°C\n湿度:{humidity}%\n风速:{wind}m/s"

@mcp.tool()
async def get_current_time() -> str:
    """获取当前时间
    
    Returns:
        格式化后的当前时间字符串
    """
    from datetime import datetime
    now = datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S")

@mcp.tool()
async def get_weather_tool(city: str) -> str:
    """获取指定城市的天气信息
    
    Args:
    
        city: 城市名称，请使用英文(如果是"武汉"，则英文为"Wuhan")
        
    Returns:
        格式化后的天气信息字符串
    """
    weather_data = await get_weather(city)
    return format_weather_data(weather_data)



    
    

if __name__ == "__main__":
    mcp.run(transport="stdio")
    
    
    
