import os
import json
import re
import asyncio
import sys
from datetime import datetime
from aiogram import Router, F, types
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, ErrorEvent, FSInputFile
from aiogram_calendar import SimpleCalendar, SimpleCalendarCallback

from database import Database
from config import ADMIN_IDS, logger
from ai_engine import groq_text_brain, groq_transcribe, groq_analyze_image
from utils import create_backup

router = Router()

# --- ДОДАТКОВА ФУНКЦІЯ: НОРМАЛІЗАЦІЯ ЧАСУ ---
def normalize_time(text_time):
    clean_time = text_time.replace('.', ':').replace(',', ':').replace(' ', ':')
    if re.match(r"^\d{1,2}:\d{2}$", clean_time):
        parts = clean_time.split(':')
        h, m = int(parts[0]), int(parts[1])
        if 0 <= h <= 23 and 0 <= m <= 59:
            return f"{h:02d}:{m:02d}"
    return None

# --- МАШИНА СТАНІВ (FSM) ---
class ReminderFSM(StatesGroup):
    waiting_for_text = State()
    waiting_for_date = State()
    waiting_for_time = State()

class EditFSM(StatesGroup):
    choosing_option = State()
    editing_text = State()
    editing_date = State()
    editing_time = State()

# --- КЛАВІАТУРИ ---
async def get_kb(user_id):
    u = await Database.get_user(user_id)
    is_toxic, spam_mode = u[0], u[4]
    
    kb = [
        [KeyboardButton(text="📅 Створити нагадування"), KeyboardButton(text="📋 Список планів")],
        [KeyboardButton(text="📍 Погода", request_location=True)],
        [KeyboardButton(text="😇 Включити Няшку" if is_toxic else "😈 Включити Бидло"), 
         KeyboardButton(text="🔔 Спам: ON" if spam_mode else "🔕 Спам: OFF")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_time_kb():
    buttons = [
        [InlineKeyboardButton(text="09:00", callback_data="time_09:00"), 
         InlineKeyboardButton(text="12:00", callback_data="time_12:00"),
         InlineKeyboardButton(text="15:00", callback_data="time_15:00")],
        [InlineKeyboardButton(text="18:00", callback_data="time_18:00"), 
         InlineKeyboardButton(text="20:00", callback_data="time_20:00"),
         InlineKeyboardButton(text="22:00", callback_data="time_22:00")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# --- АДМІН ПАНЕЛЬ ---

@router.message(Command("stats"))
async def admin_stats(m: types.Message):
    if m.from_user.id not in ADMIN_IDS: return
    u, r = await Database.get_stats()
    db_size = os.path.getsize("jarvis_db.db") / (1024 * 1024) if os.path.exists("jarvis_db.db") else 0
    await m.answer(f"📊 **Статус:**\n👥 Юзерів: `{u}`\n⏳ Планів: `{r}`\n💾 База: `{db_size:.2f} MB`", parse_mode="Markdown")

@router.message(Command("users"))
async def admin_users_list(m: types.Message):
    if m.from_user.id not in ADMIN_IDS: return
    users = await Database.get_all_users()
    msg = f"👥 **Всього користувачів:** {len(users)}\n\n"
    for u in users:
        msg += f"{'😈' if u[1] else '😇'} ID: `{u[0]}`\n"
    await m.answer(msg, parse_mode="Markdown")

@router.message(Command("all_reminders"))
async def admin_all_rems(m: types.Message):
    if m.from_user.id not in ADMIN_IDS: return
    rems = await Database.get_all_active_reminders()
    if not rems: return await m.answer("Нагадувань немає.")
    msg = "⏳ **Всі активні нагадування:**\n\n"
    for r in rems:
        msg += f"👤 `{r[1]}` | ⏰ {r[3]}\n📝 {r[2]}\n\n"
    await m.answer(msg[:4000], parse_mode="Markdown")

@router.message(Command("all_notes"))
async def admin_spy_notes(m: types.Message):
    if m.from_user.id not in ADMIN_IDS: return
    notes = await Database.get_latest_notes(limit=10)
    msg = "🕵️ **Останні 10 нотаток:**\n\n"
    for n in notes:
        msg += f"👤 `{n[0]}`: {n[1]}\n"
    await m.answer(msg[:4000], parse_mode="Markdown")

@router.message(Command("broadcast"))
async def admin_broadcast(m: types.Message):
    if m.from_user.id not in ADMIN_IDS: return
    text = m.text.replace("/broadcast", "").strip()
    if not text: return await m.answer("⚠️ Текст?")
    
    users = await Database.get_all_users()
    count = 0
    await m.answer("🚀 Починаю розсилку...")
    for u in users:
        try:
            await m.bot.send_message(user[0], f"📢 <b>Оголошення:</b>\n\n{text}", parse_mode="HTML")
            count += 1
            await asyncio.sleep(0.05)
        except: continue
    await m.answer(f"✅ Успішно: {count}")

@router.message(Command("backup"))
async def cmd_backup(m: types.Message):
    if m.from_user.id not in ADMIN_IDS: return
    backup_path = await create_backup()
    if backup_path:
        await m.answer_document(FSInputFile(backup_path), caption=f"📦 Бекап від {datetime.now()}")
        os.remove(backup_path)
    else:
        await m.answer("❌ Помилка створення бекапу.")

@router.message(Command("restart"))
async def cmd_restart(m: types.Message):
    if m.from_user.id not in ADMIN_IDS: return
    await m.answer("🔄 Перезавантажуюсь...")
    os.execv(sys.executable, ['python'] + sys.argv)

@router.message(Command("db_clean"))
async def manual_clean(m: types.Message):
    if m.from_user.id not in ADMIN_IDS: return
    await Database.clean_old_data(days=0)
    await m.answer("🧹 База очищена.")

# --- КОРИСТУВАЦЬКІ ФУНКЦІЇ ---

@router.message(Command("report"))
async def cmd_report(m: types.Message):
    text = m.text.replace("/report", "").strip()
    if not text: return await m.answer("✍️ Опишіть проблему: `/report ...`")
    for admin_id in ADMIN_IDS:
        try: await m.bot.send_message(admin_id, f"📩 **REPORT від {m.from_user.id}:**\n{text}")
        except: pass
    await m.answer("✅ Надіслано.")

@router.message(Command("note"))
async def add_note_handler(m: types.Message):
    text = m.text.replace("/note", "").strip()
    if not text: return await m.answer("✍️ Приклад: `/note текст`")
    await Database.add_note(m.from_user.id, text)
    await m.answer("✅ Збережено!")

@router.message(Command("search"))
async def search_notes_handler(m: types.Message):
    query = m.text.replace("/search", "").strip()
    if not query: return await m.answer("🔍 Що шукати?")
    res = await Database.search_notes(m.from_user.id, query)
    if not res: return await m.answer("🤷‍♂️ Пусто.")
    msg = "<b>🔎 Знайдено:</b>\n\n" + "\n".join([f"🔹 {n[0]}" for n in res])
    await m.answer(msg, parse_mode="HTML")

# --- СТВОРЕННЯ НАГАДУВАННЯ (КНОПКИ) ---

@router.message(F.text == "📅 Створити нагадування")
async def start_creation(m: types.Message, state: FSMContext):
    await m.answer("✍️ Напиши текст нагадування:", parse_mode="Markdown")
    await state.set_state(ReminderFSM.waiting_for_text)

@router.message(StateFilter(ReminderFSM.waiting_for_text))
async def step_text_saved(m: types.Message, state: FSMContext):
    await state.update_data(remind_text=m.text)
    calendar = SimpleCalendar()
    await m.answer("📅 Оберіть дату:", reply_markup=await calendar.start_calendar())
    await state.set_state(ReminderFSM.waiting_for_date)

@router.callback_query(SimpleCalendarCallback.filter(), StateFilter(ReminderFSM.waiting_for_date))
async def process_calendar(callback: types.CallbackQuery, callback_data: dict, state: FSMContext):
    calendar = SimpleCalendar()
    selected, date = await calendar.process_selection(callback, callback_data)
    if selected:
        formatted_date = date.strftime("%Y-%m-%d")
        await state.update_data(remind_date=formatted_date)
        await callback.message.edit_text(f"📅 Дата: {formatted_date}\n⏰ Оберіть час або напишіть (ГГ:ХХ):", reply_markup=get_time_kb())
        await state.set_state(ReminderFSM.waiting_for_time)

@router.callback_query(F.data.startswith("time_"), StateFilter(ReminderFSM.waiting_for_time))
async def process_time_btn(callback: types.CallbackQuery, state: FSMContext):
    time_val = callback.data.split("_")[1]
    await finalize_reminder(callback.message, time_val, state, callback.from_user.id)
    await callback.answer()

@router.message(StateFilter(ReminderFSM.waiting_for_time))
async def process_time_text(m: types.Message, state: FSMContext):
    clean_time = normalize_time(m.text)
    if not clean_time:
        return await m.answer("⚠️ Невірний формат. Спробуйте так: 14:30")
    await finalize_reminder(m, clean_time, state, m.from_user.id)

async def finalize_reminder(message: types.Message, time_str: str, state: FSMContext, user_id: int):
    data = await state.get_data()
    full_datetime = f"{data['remind_date']} {time_str}:00"
    await Database.add_reminder(user_id, message.chat.id, data['remind_text'], full_datetime, recurrence=None)
    await message.answer(f"✅ **Створено!**\n📌 {data['remind_text']}\n⏰ {full_datetime}", parse_mode="Markdown", reply_markup=await get_kb(user_id))
    await state.clear()

# --- СПИСОК ПЛАНІВ ТА РЕДАГУВАННЯ ---

@router.message(F.text == "📋 Список планів")
async def show_list(m: types.Message):
    rows = await Database.get_active_reminders(m.from_user.id)
    if not rows: return await m.answer("У вас немає активних планів 🤷‍♂️")
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    await m.answer("📋 **Ваші плани:**", parse_mode="Markdown")
    
    for r in rows:
        rid, r_time, r_text = r
        r_date = r_time.split(" ")[0]
        r_clock = r_time.split(" ")[1][:5]
        date_info = f"Сьогодні о {r_clock}" if r_date == today_str else f"{r_date} о {r_clock}"
        
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✏️ Змінити", callback_data=f"edit_{rid}"),
            InlineKeyboardButton(text="❌ Видалити", callback_data=f"del_{rid}")
        ]])
        await m.answer(f"📝 *{r_text}*\n⏰ {date_info}", parse_mode="Markdown", reply_markup=kb)

@router.callback_query(F.data.startswith("edit_"))
async def edit_start(call: types.CallbackQuery, state: FSMContext):
    rid = call.data.split("_")[1]
    await state.update_data(edit_id=rid)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Змінити текст", callback_data="edopt_text")],
        [InlineKeyboardButton(text="⏰ Змінити час", callback_data="edopt_time")],
        [InlineKeyboardButton(text="🔙 Скасувати", callback_data="edopt_cancel")]
    ])
    await call.message.answer("Що хочемо змінити?", reply_markup=kb)
    await state.set_state(EditFSM.choosing_option)
    await call.answer()

@router.callback_query(F.data.startswith("edopt_"), StateFilter(EditFSM.choosing_option))
async def edit_option_handler(call: types.CallbackQuery, state: FSMContext):
    action = call.data.split("_")[1]
    if action == "cancel":
        await call.message.delete()
        await state.clear()
        return
    if action == "text":
        await call.message.edit_text("Введіть новий текст:")
        await state.set_state(EditFSM.editing_text)
    elif action == "time":
        calendar = SimpleCalendar()
        await call.message.edit_text("Оберіть нову дату:", reply_markup=await calendar.start_calendar())
        await state.set_state(EditFSM.editing_date)

@router.message(StateFilter(EditFSM.editing_text))
async def save_new_text(m: types.Message, state: FSMContext):
    data = await state.get_data()
    await Database.update_reminder_field(data['edit_id'], "remind_text", m.text)
    await m.answer("✅ Текст оновлено!", reply_markup=await get_kb(m.from_user.id))
    await state.clear()

@router.callback_query(SimpleCalendarCallback.filter(), StateFilter(EditFSM.editing_date))
async def edit_date_process(callback: types.CallbackQuery, callback_data: dict, state: FSMContext):
    calendar = SimpleCalendar()
    selected, date = await calendar.process_selection(callback, callback_data)
    if selected:
        await state.update_data(new_date=date.strftime("%Y-%m-%d"))
        await callback.message.edit_text("Введіть новий час:", reply_markup=get_time_kb())
        await state.set_state(EditFSM.editing_time)

@router.callback_query(F.data.startswith("time_"), StateFilter(EditFSM.editing_time))
async def edit_time_btn(callback: types.CallbackQuery, state: FSMContext):
    time_val = callback.data.split("_")[1]
    await save_new_time(callback.message, time_val, state)

@router.message(StateFilter(EditFSM.editing_time))
async def edit_time_text(m: types.Message, state: FSMContext):
    clean_time = normalize_time(m.text)
    if not clean_time:
        return await m.answer("⚠️ Невірний формат.")
    await save_new_time(m, clean_time, state)

async def save_new_time(message, time_val, state):
    data = await state.get_data()
    full_dt = f"{data['new_date']} {time_val}:00"
    await Database.update_reminder_field(data['edit_id'], "remind_time", full_dt)
    await message.answer(f"✅ Час перенесено на {full_dt}", reply_markup=await get_kb(message.chat.id))
    await state.clear()

@router.callback_query(F.data.startswith("del_"))
async def del_rem(call: types.CallbackQuery):
    rid = call.data.split("_")[1]
    await Database.delete_reminder(rid)
    await call.message.delete()
    await call.answer("Видалено")

# --- ІНШІ ХЕНДЛЕРИ ---

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

@router.message(CommandStart())
async def start(m: types.Message, state: FSMContext):
    await state.clear()
    await Database.get_user(m.from_user.id)
    await m.answer("Йо. Я на місці.", reply_markup=await get_kb(m.from_user.id))

@router.message(F.text)
async def text_handler(m: types.Message):
    ignored = ["📋 Список планів", "📍 Погода", "📅 Створити нагадування", 
               "😈 Включити Бидло", "😇 Включити Няшку", "🔔 Спам: ON", "🔕 Спам: OFF"]
    if m.text in ignored: return
    if m.text.startswith("/"): return
    await process_smart(m, m.text)

async def process_smart(m, text):
    u = await Database.get_user(m.from_user.id)
    res = await groq_text_brain(text, m.from_user.id, u[0], u[1], u[2], bool(m.forward_origin))
    
    if res:
        reply = res.get('reply', '...')
        await Database.add_to_context(m.from_user.id, "user", m.text)
        await Database.add_to_context(m.from_user.id, "assistant", reply)
        
        if res.get('save_note'):
            await Database.add_note(m.from_user.id, res['save_note'])
            reply += "\n\n✅ (Записав у нотатки)"

        if res.get('is_reminder') and res.get('time'):
            await Database.add_reminder(m.from_user.id, m.chat.id, res['task'], res['time'], res['recurrence'])
            reply += f"\n⏰ (Нагадування на {res['time']})"

        await m.answer(reply)

# --- ЛОВЛЯ ПОМИЛОК ---
@router.error()
async def error_handler(event: ErrorEvent):
    logger.error(f"Critical Error: {event.exception}", exc_info=True)
    if ADMIN_IDS:
        try:
            await event.update.bot.send_message(ADMIN_IDS[0], f"⚠️ **CRITICAL ERROR**\n`{event.exception}`", parse_mode="Markdown")
        except: pass
