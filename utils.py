import re
import aiohttp
import shutil
import os
from datetime import datetime
from config import logger, DB_NAME
from youtube_transcript_api import YouTubeTranscriptApi

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

async def create_backup():
    """Створює копію бази даних"""
    try:
        backup_name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        shutil.copyfile(DB_NAME, backup_name)
        return backup_name
    except Exception as e:
        logger.error(f"Backup error: {e}")
        return None

def get_youtube_id(url):
    """Витягує ID відео з посилання"""
    regex = r"(?:v=|\/)([0-9A-Za-z_-]{11}).*"
    match = re.search(regex, url)
    return match.group(1) if match else None

async def get_video_transcript(video_id, lang="uk"):
    """Отримує текст субтитрів"""
    try:
        languages = ['uk', 'en'] if lang == 'uk' else ['en', 'uk']
        transcript_list = await YouTubeTranscriptApi.get_transcript(video_id, languages=languages)
        formatter = lambda x: " ".join([d['text'] for d in x])
        # Виконуємо синхронну функцію в окремому потоці, щоб не блокувати бота
        return formatter(transcript_list)[:15000]
    except Exception as e:
        logger.error(f"YouTube error: {e}")
        return None
