import aiohttp
import json
import base64
from datetime import datetime
import pytz
from config import GROQ_KEY, TIMEZONE, logger
from utils import clean_json_response, get_weather

MODEL_TEXT = "llama-3.3-70b-versatile"
MODEL_VISION = "llama-3.2-11b-vision-preview"
MODEL_AUDIO = "whisper-large-v3"

async def groq_transcribe(file_path):
    url = "https://api.groq.com/openai/v1/audio/transcriptions"
    try:
        with open(file_path, 'rb') as f:
            data = aiohttp.FormData()
            data.add_field('file', f)
            data.add_field('model', MODEL_AUDIO)
            data.add_field('language', 'uk')
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers={"Authorization": f"Bearer {GROQ_KEY}"}, data=data) as resp:
                    return (await resp.json()).get('text', '')
    except Exception as e:
        logger.error(f"Transcribe error: {e}")
        return ""

async def groq_analyze_image(text_prompt, image_path, is_toxic):
    with open(image_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode('utf-8')
    style = "Be rude, use ukrainian profanity" if is_toxic else "Be sweet and helpful"
    payload = {
        "model": MODEL_VISION,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": f"{text_prompt}. Style: {style} (Ukrainian)"},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}}
        ]}],
        "max_tokens": 400
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_KEY}"}, json=payload) as resp:
                return (await resp.json())['choices'][0]['message']['content']
    except: return "Не бачу картинки."

async def groq_text_brain(text, user_id, is_toxic, lat, lon, is_forwarded=False):
    # Імпорт тут, щоб не було циклічності
    from database import Database
    
    # 1. Отримуємо нотатки
    notes = await Database.get_recent_notes(user_id)
    
    # 2. Отримуємо історію діалогу (контекст)
    history = await Database.get_context(user_id)
    
    weather_info = "Unknown"
    if lat and lon:
        w = await get_weather(lat, lon)
        if w: weather_info = f"{w['temp']}°C, Rain: {w['rain']}%"

    now = datetime.now(pytz.timezone(TIMEZONE))
    persona = "ТИ - БИДЛО (СУРЖИК, МАТИ)" if is_toxic else "ТИ - МИЛА НЯШКА (ЕМОДЗІ, ДОБРОТА)"

    system_prompt = f"""
    {persona}. Language: Ukrainian.
    Time: {now.strftime("%Y-%m-%d %H:%M:%S")}. Weather: {weather_info}.
    User Notes (Second Brain): {notes}. Forwarded message: {is_forwarded}.
    INSTRUCTION: 
    1. If user asks to save something -> return "save_note": "text".
    2. If user asks to remind -> return "is_reminder": true.
    3. Else -> just chat.
    JSON OUTPUT ONLY:
    {{
        "is_reminder": boolean,
        "task": "string|null",
        "time": "YYYY-MM-DD HH:MM:SS|null",
        "recurrence": "daily"|"weekly"|null,
        "save_note": "string|null",
        "reply": "string"
    }}
    """
    
    messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": text}]
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_KEY}"}, 
                json={"model": MODEL_TEXT, "messages": messages, "response_format": {"type": "json_object"}}) as resp:
                data = await resp.json()
                content = data['choices'][0]['message']['content']
                return json.loads(clean_json_response(content))
    except Exception as e:
        logger.error(f"Brain error: {e}")
        return None
