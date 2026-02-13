import re
import aiohttp
from config import logger

def clean_json_response(text):
    """Витягує чистий JSON з відповіді ШІ"""
    try:
        match = re.search(r"(\{.*\})", text, re.DOTALL)
        return match.group(1) if match else text
    except: return text

async def get_weather(lat, lon):
    """Отримує погоду по координатах"""
    if not lat or not lon: return None
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m&daily=precipitation_probability_max&timezone=auto"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as resp:
                if resp.status != 200: return None
                data = await resp.json()
                return {
                    "temp": data['current']['temperature_2m'],
                    "rain": data['daily']['precipitation_probability_max'][0]
                }
    except Exception as e:
        logger.error(f"Weather error: {e}")
        return None
