import os
import json
from datetime import datetime
from aiogram import Router, F, types
from aiogram.filters import CommandStart
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from database import Database
from ai_engine import groq_text_brain, groq_transcribe, groq_analyze_image

router = Router()

async def get_kb(user_id):
    u = await Database.get_user(user_id)
    is_toxic, spam_mode = u[0], u[4]
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📋 Список планів"), KeyboardButton(text="📍 Погода", request_location=True)],
        [KeyboardButton(text="😇 Включити Няшку" if is_toxic else "😈 Включити Бидло"), 
         KeyboardButton(text="🔔 Спам: ON" if spam_mode else "🔕 Спам: OFF")]
    ], resize_keyboard=True)

@router.message(CommandStart())
async def start(m: types.Message):
    await Database.get_user(m.from_user.id)
    await m.answer("Йо. Я на місці.", reply_markup=await get_kb(m.from_user.id))

@router.message(F.text.in_({"😈 Включити Бидло", "😇 Включити Няшку"}))
async def toggle_toxic(m: types.Message):
    u = await Database.get_user(m.from_user.id)
    await Database.update_user(m.from_user.id, is_toxic=not u[0])
    await m.answer("Режим змінено.", reply_markup=await get_kb(m.from_user.id))

@router.message(F.text.in_({"🔔 Спам: ON", "🔕 Спам: OFF"}))
async def toggle_spam(m: types.Message):
    u = await Database.get_user(m.from_user.id)
    await Database.update_user(m.from_user.id, spam_mode=not u[4])
    await m.answer("Режим спаму змінено.", reply_markup=await get_kb(m.from_user.id))

@router.message(F.voice)
async def voice_handler(m: types.Message):
    # Використовуємо m.bot замість передачі аргументу
    file = await m.bot.get_file(m.voice.file_id)
    path = f"voice_{m.from_user.id}.ogg"
    await m.bot.download_file(file.file_path, path)
    
    text = await groq_transcribe(path)
    if os.path.exists(path): os.remove(path)
    
    await m.reply(f"🗣 {text}")
    await process_smart(m, text)

@router.message(F.photo)
async def photo_handler(m: types.Message):
    file = await m.bot.get_file(m.photo[-1].file_id)
    path = f"photo_{m.from_user.id}.jpg"
    await m.bot.download_file(file.file_path, path)
    
    u = await Database.get_user(m.from_user.id)
    ans = await groq_analyze_image(m.caption or "Describe", path, u[0])
    
    if os.path.exists(path): os.remove(path)
    await m.reply(ans)

@router.message(F.location)
async def location_handler(m: types.Message):
    await Database.update_user(m.from_user.id, lat=m.location.latitude, lon=m.location.longitude)
    await m.answer("📍 Локацію записав.")

@router.message(F.text == "📋 Список планів")
async def show_list(m: types.Message):
    # Повертаємо логіку списку!
    import aiosqlite
    from config import DB_NAME
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT id, remind_time, remind_text FROM reminders WHERE user_id=? AND status IN ('pending','spamming')", (m.from_user.id,)) as c:
            rows = await c.fetchall()
    
    if not rows: return await m.answer("Пусто.")
    
    buttons = []
    for r in rows:
        # r[0]=id, r[1]=time, r[2]=text
        buttons.append([InlineKeyboardButton(text=f"❌ {r[1][5:16]} | {r[2][:10]}", callback_data=f"del_{r[0]}")])
        
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await m.answer("Твої плани:", reply_markup=kb)

@router.callback_query(F.data.startswith("del_"))
async def del_rem(call: types.CallbackQuery):
    rid = call.data.split("_")[1]
    import aiosqlite
    from config import DB_NAME
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM reminders WHERE id=?", (rid,))
        await db.commit()
    await call.message.delete()
    await call.answer("Видалено")

@router.callback_query(F.data.startswith("confirm_"))
async def confirm_rem(call: types.CallbackQuery):
    rid = call.data.split("_")[1]
    import aiosqlite
    from config import DB_NAME
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE reminders SET status='fired' WHERE id=?", (rid,))
        await db.commit()
    await call.message.edit_text("Ок, зроблено.")

@router.message(F.text)
async def text_handler(m: types.Message):
    if m.text in ["📋 Список планів", "📍 Погода"]: return
    await process_smart(m, m.text)

async def process_smart(m, text):
    u = await Database.get_user(m.from_user.id)
    # u[0]=is_toxic, u[1]=lat, u[2]=lon, u[3]=memory
    res = await groq_text_brain(text, m.from_user.id, u[0], u[3], u[1], u[2], bool(m.forward_origin))
    
    if not res: return await m.answer("Еррор.")
    
    reply = res.get('reply', '...')
    if res.get('is_reminder') and res.get('time'):
        await Database.add_reminder(m.from_user.id, m.chat.id, res['task'], res['time'], res['recurrence'])
        reply += f"\n⏰ (Нагадування на {res['time']})"

    if res.get('save_note'):
        await Database.add_note(m.from_user.id, res['save_note'], datetime.now().isoformat())
        reply += "\n💾 (Зберіг)"

    try: mem = json.loads(u[3])
    except: mem = []
    mem.append({"role": "user", "content": text})
    mem.append({"role": "assistant", "content": reply})
    await Database.update_user(m.from_user.id, memory_json=json.dumps(mem[-10:]))
    await m.answer(reply)
