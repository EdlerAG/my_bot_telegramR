import asyncio
import logging
import json
import sys
import os
import base64
import re
from datetime import datetime, timedelta

import pytz
import aiohttp
import aiosqlite
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ================= КОНФІГУРАЦІЯ =================
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
GROQ_KEY = os.getenv("GROQ_API_KEY")
ADMIN_ID = os.getenv("ADMIN_ID")
DEFAULT_TZ = os.getenv("TIMEZONE", "Europe/Kyiv")
DB_NAME = "jarvis_db.db"

if not TOKEN or not GROQ_KEY:
    sys.exit("❌ ПОМИЛКА: Немає ключів у файлі .env!")

# Моделі
MODEL_TEXT = "llama-3.3-70b-versatile"
MODEL_VISION = "llama-3.2-11b-vision-preview"
MODEL_AUDIO = "whisper-large-v3"

# Логування
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp = Dispatcher()
scheduler = AsyncIOScheduler()

# ================= БАЗА ДАНИХ =================
class Database:
    @staticmethod
    async def init():
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, 
                    user_id INTEGER, 
                    chat_id INTEGER, 
                    remind_text TEXT, 
                    remind_time TEXT,
                    recurrence TEXT DEFAULT NULL,
                    status TEXT DEFAULT 'pending'
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY, 
                    is_toxic BOOLEAN DEFAULT 0, 
                    spam_mode BOOLEAN DEFAULT 0,
                    lat REAL DEFAULT NULL,
                    lon REAL DEFAULT NULL,
                    memory_json TEXT DEFAULT '[]'
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    content TEXT,
                    created_at TEXT
                )
            """)
            await db.commit()

    @staticmethod
    async def get_user(user_id):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
            await db.commit()
            async with db.execute("SELECT is_toxic, lat, lon, memory_json, spam_mode FROM users WHERE user_id=?", (user_id,)) as c:
                return await c.fetchone()

    @staticmethod
    async def update_user(user_id, **kwargs):
        set_clause = ", ".join([f"{k}=?" for k in kwargs.keys()])
        values = list(kwargs.values()) + [user_id]
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(f"UPDATE users SET {set_clause} WHERE user_id=?", values)
            await db.commit()

# ================= AI ЛОГІКА =================
def clean_json_response(text):
    try:
        match = re.search(r"(\{.*\})", text, re.DOTALL)
        return match.group(1) if match else text
    except: return text

async def get_weather(lat, lon):
    if not lat or not lon: return None
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m&daily=precipitation_probability_max&timezone=auto"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as resp:
                data = await resp.json()
                return {"temp": data['current']['temperature_2m'], "rain": data['daily']['precipitation_probability_max'][0]}
    except: return None

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
    except: return ""

async def groq_analyze_image(text_prompt, image_path, is_toxic):
    with open(image_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode('utf-8')
    style = "Be rude, use ukrainian profanity" if is_toxic else "Be sweet and helpful"
    payload = {
        "model": MODEL_VISION,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": f"{text_prompt}. Style: {style} (Ukrainian)"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}}
            ]
        }],
        "max_tokens": 400
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_KEY}"}, json=payload) as resp:
                return (await resp.json())['choices'][0]['message']['content']
    except: return "Не бачу картинки."

async def groq_text_brain(text, user_id, is_toxic, memory_json, lat, lon, is_forwarded=False):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT content FROM notes WHERE user_id=? ORDER BY id DESC LIMIT 5", (user_id,)) as c:
            notes = [row[0] for row in await c.fetchall()]
    
    weather_info = "Unknown"
    if lat and lon:
        w = await get_weather(lat, lon)
        if w: weather_info = f"{w['temp']}°C, Rain: {w['rain']}%"

    now = datetime.now(pytz.timezone(DEFAULT_TZ))
    
    if is_toxic:
        persona = "ТИ - БИДЛО І ГОПНИК. Спілкуйся суржиком, груби, використовуй мати (нахуй, бля, чорт). Ти не асистент, ти пацан з району."
    else:
        persona = "ТИ - МИЛА НЯШКА. Спілкуйся дуже ніжно, використовуй емодзі (💖, ✨), піклуйся про юзера."

    system_prompt = f"""
    {persona}
    Current Time: {now.strftime("%Y-%m-%d %H:%M:%S")}. Weather: {weather_info}.
    Notes: {notes}. Forwarded: {is_forwarded}.
    
    INSTRUCTION:
    If user asks to set a reminder (e.g. 'remind me in 10 mins'), set 'is_reminder': true.
    If just chatting or insulting, 'is_reminder': false.
    
    JSON OUTPUT ONLY:
    {{
        "is_reminder": boolean,
        "task": "string or null",
        "time": "YYYY-MM-DD HH:MM:SS or null",
        "recurrence": "daily"|"weekly"|null,
        "save_note": "string or null",
        "reply": "string (your text response)"
    }}
    """
    try:
        history = json.loads(memory_json)[-6:]
    except: history = []

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
        logger.error(f"AI Error: {e}")
        return None

# ================= ОБРОБНИКИ =================
async def get_kb(user_id):
    u = await Database.get_user(user_id)
    is_toxic, spam_mode = u[0], u[4]
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📋 Список планів"), KeyboardButton(text="📍 Погода", request_location=True)],
        [KeyboardButton(text="😇 Включити Няшку" if is_toxic else "😈 Включити Бидло"), 
         KeyboardButton(text="🔔 Спам: ON" if spam_mode else "🔕 Спам: OFF")]
    ], resize_keyboard=True)

@dp.message(CommandStart())
async def start(m: types.Message):
    await Database.get_user(m.from_user.id)
    await m.answer("Йо. Я на місці.", reply_markup=await get_kb(m.from_user.id))

@dp.message(F.text.in_({"😈 Включити Бидло", "😇 Включити Няшку"}))
async def toggle_toxic(m: types.Message):
    u = await Database.get_user(m.from_user.id)
    await Database.update_user(m.from_user.id, is_toxic=not u[0])
    await m.answer("Режим змінено.", reply_markup=await get_kb(m.from_user.id))

@dp.message(F.text.in_({"🔔 Спам: ON", "🔕 Спам: OFF"}))
async def toggle_spam(m: types.Message):
    u = await Database.get_user(m.from_user.id)
    await Database.update_user(m.from_user.id, spam_mode=not u[4])
    await m.answer("Режим спаму змінено.", reply_markup=await get_kb(m.from_user.id))

@dp.message(F.voice)
async def voice_handler(m: types.Message):
    file = await bot.get_file(m.voice.file_id)
    path = f"voice_{m.from_user.id}.ogg"
    await bot.download_file(file.file_path, path)
    text = await groq_transcribe(path)
    if os.path.exists(path): os.remove(path)
    await m.reply(f"🗣 {text}")
    await process_smart(m, text)

@dp.message(F.photo)
async def photo_handler(m: types.Message):
    file = await bot.get_file(m.photo[-1].file_id)
    path = f"photo_{m.from_user.id}.jpg"
    await bot.download_file(file.file_path, path)
    u = await Database.get_user(m.from_user.id)
    ans = await groq_analyze_image(m.caption or "Describe", path, u[0])
    if os.path.exists(path): os.remove(path)
    await m.reply(ans)

@dp.message(F.text)
async def text_handler(m: types.Message):
    if m.text in ["📋 Список планів", "📍 Погода"]: return # Ігнор кнопок
    await process_smart(m, m.text)

async def process_smart(m, text):
    u = await Database.get_user(m.from_user.id)
    res = await groq_text_brain(text, m.from_user.id, u[0], u[3], u[1], u[2], bool(m.forward_origin))
    if not res: return await m.answer("Еррор.")
    
    reply = res.get('reply', '...')
    
    if res.get('is_reminder') and res.get('time'):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("INSERT INTO reminders (user_id, chat_id, remind_text, remind_time, recurrence) VALUES (?,?,?,?,?)",
                             (m.from_user.id, m.chat.id, res['task'], res['time'], res['recurrence']))
            await db.commit()
        reply += f"\n⏰ (Нагадування на {res['time']})"

    if res.get('save_note'):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("INSERT INTO notes (user_id, content, created_at) VALUES (?,?,?)",
                             (m.from_user.id, res['save_note'], datetime.now().isoformat()))
            await db.commit()
        reply += "\n💾 (Зберіг)"

    # Memory update
    try: mem = json.loads(u[3])
    except: mem = []
    mem.append({"role": "user", "content": text})
    mem.append({"role": "assistant", "content": reply})
    await Database.update_user(m.from_user.id, memory_json=json.dumps(mem[-10:]))
    
    await m.answer(reply)

# ================= СПИСОК / ВИДАЛЕННЯ =================
@dp.message(F.text == "📋 Список планів")
async def show_list(m: types.Message):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT id, remind_time, remind_text FROM reminders WHERE user_id=? AND status IN ('pending','spamming')", (m.from_user.id,)) as c:
            rows = await c.fetchall()
    if not rows: return await m.answer("Пусто.")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"❌ {r[1][5:16]} | {r[2][:10]}", callback_data=f"del_{r[0]}")] for r in rows
    ])
    await m.answer("Твої плани:", reply_markup=kb)

@dp.callback_query(F.data.startswith("del_"))
async def del_rem(call: types.CallbackQuery):
    rid = call.data.split("_")[1]
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM reminders WHERE id=?", (rid,))
        await db.commit()
    await call.message.delete()
    await call.answer("Видалено")

@dp.callback_query(F.data.startswith("confirm_"))
async def confirm_rem(call: types.CallbackQuery):
    rid = call.data.split("_")[1]
    # Тут спрощена логіка повторень, щоб код вліз
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE reminders SET status='fired' WHERE id=?", (rid,))
        await db.commit()
    await call.message.edit_text("Ок, зроблено.")

# ================= ЧЕКЕР =================
async def checker():
    now = datetime.now(pytz.timezone(DEFAULT_TZ)).strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_NAME) as db:
        rows = await (await db.execute("SELECT id, chat_id, remind_text, user_id, status FROM reminders WHERE (status='pending' AND remind_time <= ?) OR status='spamming'", (now,))).fetchall()
        for r in rows:
            u = await Database.get_user(r[3]) # r[3] = user_id
            is_spam = u[4]
            
            if is_spam:
                await db.execute("UPDATE reminders SET status='spamming' WHERE id=?", (r[0],))
                kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Зробив", callback_data=f"confirm_{r[0]}")]])
                try: await bot.send_message(r[1], f"🤬 РОБИ ДАВАЙ: {r[2]}", reply_markup=kb)
                except: pass
            else:
                if r[4] == 'pending':
                    await db.execute("UPDATE reminders SET status='fired' WHERE id=?", (r[0],))
                    try: await bot.send_message(r[1], f"🔔 Нагадування: {r[2]}")
                    except: pass
        await db.commit()

async def main():
    await Database.init()
    scheduler.add_job(checker, 'interval', seconds=30)
    scheduler.start()
    logger.info("Started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
