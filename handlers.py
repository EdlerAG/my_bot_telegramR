import os
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
from ai_engine import groq_text_brain, groq_transcribe, groq_analyze_image, groq_summarize_video
from utils import create_backup, get_youtube_id
from locales import t

router = Router()

def normalize_time(text_time):
    clean_time = text_time.replace('.', ':').replace(',', ':').replace(' ', ':')
    if re.match(r"^\d{1,2}:\d{2}$", clean_time):
        parts = clean_time.split(':')
        h, m = int(parts[0]), int(parts[1])
        if 0 <= h <= 23 and 0 <= m <= 59:
            return f"{h:02d}:{m:02d}"
    return None

class ReminderFSM(StatesGroup):
    waiting_for_text = State()
    waiting_for_date = State()
    waiting_for_time = State()

class EditFSM(StatesGroup):
    choosing_option = State()
    editing_text = State()
    editing_date = State()
    editing_time = State()

# --- ПЕРЕВІРКА НА БАН ---
async def is_banned(user_id):
    u = await Database.get_user(user_id)
    return u[7] # 7-й індекс це is_banned

# --- КЛАВІАТУРИ ---
async def get_kb(user_id):
    u = await Database.get_user(user_id)
    lang = u[5]
    kb = [
        [KeyboardButton(text=t("btn_create_rem", lang)), KeyboardButton(text=t("btn_list_rem", lang))],
        [KeyboardButton(text=t("btn_weather", lang), request_location=True)],
        [KeyboardButton(text=t("btn_settings", lang))]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

async def get_settings_kb(user_id):
    u = await Database.get_user(user_id)
    # 0=toxic, 4=spam, 5=lang, 6=morning
    is_toxic, spam_mode, lang, morning = u[0], u[4], u[5], u[6]
    
    kb = [
        [InlineKeyboardButton(text=t("mode_toxic", lang) if is_toxic else t("mode_nice", lang), callback_data="toggle_toxic")],
        [InlineKeyboardButton(text=t("spam_on", lang) if spam_mode else t("spam_off", lang), callback_data="toggle_spam")],
        [InlineKeyboardButton(text=t("morning_on", lang) if morning else t("morning_off", lang), callback_data="toggle_morning")],
        [InlineKeyboardButton(text=t("lang_btn", lang), callback_data="toggle_lang")],
        [InlineKeyboardButton(text="❌ Close", callback_data="close_settings")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

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

# --- АДМІН ПАНЕЛЬ (Відновлені команди) ---

@router.message(Command("stats"))
async def admin_stats(m: types.Message):
    if m.from_user.id not in ADMIN_IDS: return
    u, r = await Database.get_stats()
    db_size = os.path.getsize("jarvis_db.db") / (1024 * 1024) if os.path.exists("jarvis_db.db") else 0
    await m.answer(f"📊 **Статус:**\n👥 Юзерів: `{u}`\n⏳ Активних планів: `{r}`\n💾 База: `{db_size:.2f} MB`", parse_mode="Markdown")

@router.message(Command("users"))
async def admin_users_list(m: types.Message):
    if m.from_user.id not in ADMIN_IDS: return
    users = await Database.get_all_users() # повертає кортежі
    msg = f"👥 **Всього користувачів:** {len(users)}\n\n"
    # u[0]=id, u[1]=toxic, u[2]=lat, u[3]=lon, u[4]=spam, u[5]=lang, u[6]=morning
    for u in users:
        icon = '🇬🇧' if u[5] == 'en' else '🇺🇦'
        mode = '😈' if u[1] else '😇'
        msg += f"{icon}{mode} `{u[0]}`\n"
    await m.answer(msg[:4000], parse_mode="Markdown")

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
            await m.bot.send_message(u[0], f"📢 <b>Оголошення:</b>\n\n{text}", parse_mode="HTML")
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

# --- БАН СИСТЕМА ---

@router.message(Command("ban"))
async def admin_ban(m: types.Message):
    if m.from_user.id not in ADMIN_IDS: return
    try:
        target_id = int(m.text.split()[1])
        await Database.update_user(target_id, is_banned=True)
        await m.answer(f"🔨 Користувача {target_id} забанено.")
    except: await m.answer("⚠️ Формат: `/ban 123456`", parse_mode="Markdown")

@router.message(Command("unban"))
async def admin_unban(m: types.Message):
    if m.from_user.id not in ADMIN_IDS: return
    try:
        target_id = int(m.text.split()[1])
        await Database.update_user(target_id, is_banned=False)
        await m.answer(f"🕊 Користувача {target_id} розбанено.")
    except: await m.answer("⚠️ Формат: `/unban 123456`", parse_mode="Markdown")

# --- ЗВОРОТНІЙ ЗВ'ЯЗОК (REPORT & REPLY) ---

@router.message(F.reply_to_message)
async def admin_reply_handler(m: types.Message):
    """Адмін відповідає на репорт через Reply"""
    if m.from_user.id not in ADMIN_IDS: return
    orig_text = m.reply_to_message.text
    if not orig_text or "📩 REPORT" not in orig_text: return
    
    try:
        # Шукаємо ID у форматі "REPORT 12345:"
        user_id_match = re.search(r"REPORT (\d+):", orig_text)
        if user_id_match:
            user_id = int(user_id_match.group(1))
            u = await Database.get_user(user_id)
            lang = u[5]
            
            await m.bot.send_message(user_id, f"{t('got_admin_reply', lang)}\n{m.text}", parse_mode="HTML")
            await m.answer("✅ Відповідь доставлена.")
    except Exception as e:
        await m.answer(f"❌ Помилка: {e}")

@router.message(Command("report"))
async def cmd_report(m: types.Message):
    if await is_banned(m.from_user.id): return
    text = m.text.replace("/report", "").strip()
    u = await Database.get_user(m.from_user.id)
    lang = u[5]
    
    if not text: return await m.answer("✍️ ...")
    
    sent_count = 0
    for admin_id in ADMIN_IDS:
        try: 
            await m.bot.send_message(
                admin_id, 
                f"📩 REPORT {m.from_user.id}:\nUser: @{m.from_user.username}\n\n{text}"
            )
            sent_count += 1
        except: pass
    
    if sent_count > 0:
        await m.answer("✅", reply_markup=await get_kb(m.from_user.id))

# --- НАЛАШТУВАННЯ (SETTINGS) ---

@router.message(Command("settings"))
@router.message(F.text.in_({"⚙️ Налаштування", "⚙️ Settings"}))
async def open_settings(m: types.Message):
    if await is_banned(m.from_user.id): return
    u = await Database.get_user(m.from_user.id)
    await m.answer(t("settings_title", u[5]), reply_markup=await get_settings_kb(m.from_user.id), parse_mode="HTML")

@router.callback_query(F.data == "toggle_toxic")
async def settings_toggle_toxic(call: types.CallbackQuery):
    u = await Database.get_user(call.from_user.id)
    await Database.update_user(call.from_user.id, is_toxic=not u[0])
    await call.message.edit_reply_markup(reply_markup=await get_settings_kb(call.from_user.id))

@router.callback_query(F.data == "toggle_spam")
async def settings_toggle_spam(call: types.CallbackQuery):
    u = await Database.get_user(call.from_user.id)
    await Database.update_user(call.from_user.id, spam_mode=not u[4])
    await call.message.edit_reply_markup(reply_markup=await get_settings_kb(call.from_user.id))

@router.callback_query(F.data == "toggle_morning")
async def settings_toggle_morning(call: types.CallbackQuery):
    u = await Database.get_user(call.from_user.id)
    await Database.update_user(call.from_user.id, morning_briefing=not u[6])
    await call.message.edit_reply_markup(reply_markup=await get_settings_kb(call.from_user.id))

@router.callback_query(F.data == "toggle_lang")
async def settings_toggle_lang(call: types.CallbackQuery):
    u = await Database.get_user(call.from_user.id)
    new_lang = "en" if u[5] == "uk" else "uk"
    await Database.update_user(call.from_user.id, language=new_lang)
    await call.message.delete()
    # Оновлюємо клавіатуру на нову мову
    await call.message.answer(t("changed", new_lang), reply_markup=await get_kb(call.from_user.id))

@router.callback_query(F.data == "close_settings")
async def close_settings(call: types.CallbackQuery):
    await call.message.delete()

# --- START & ONBOARDING ---

@router.message(CommandStart())
async def start(m: types.Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇺🇦 Українська", callback_data="set_lang_uk"),
         InlineKeyboardButton(text="🇬🇧 English", callback_data="set_lang_en")]
    ])
    await m.answer("👋 Welcome! Please choose your language / Оберіть мову:", reply_markup=kb)

@router.callback_query(F.data.startswith("set_lang_"))
async def set_language_start(call: types.CallbackQuery):
    lang_code = call.data.split("_")[2]
    await Database.update_user(call.from_user.id, language=lang_code)
    welcome_text = t("welcome", lang_code) + "\n\n" + t("features", lang_code)
    await call.message.delete()
    await call.message.answer(welcome_text, parse_mode="HTML", reply_markup=await get_kb(call.from_user.id))

# --- YOUTUBE HANDLER ---
@router.message(F.text.regexp(r"(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})"))
async def youtube_handler(m: types.Message):
    if await is_banned(m.from_user.id): return
    u = await Database.get_user(m.from_user.id)
    lang = u[5]
    
    video_id = get_youtube_id(m.text)
    if not video_id: return
    
    status_msg = await m.reply(t("yt_processing", lang))
    summary = await groq_summarize_video(video_id, lang)
    
    await status_msg.delete()
    if summary:
        await m.reply(f"{t('yt_summary_title', lang)}{summary}", parse_mode="Markdown")
    else:
        await m.reply(t("yt_error", lang))

# --- REMINDERS & NOTES ---

@router.message(Command("note"))
async def add_note_handler(m: types.Message):
    if await is_banned(m.from_user.id): return
    u = await Database.get_user(m.from_user.id)
    text = m.text.replace("/note", "").strip()
    if not text: return
    await Database.add_note(m.from_user.id, text)
    await m.answer(t("saved_note", u[5]))

@router.message(Command("search"))
async def search_notes_handler(m: types.Message):
    if await is_banned(m.from_user.id): return
    u = await Database.get_user(m.from_user.id)
    query = m.text.replace("/search", "").strip()
    if not query: return
    res = await Database.search_notes(m.from_user.id, query)
    if not res: return await m.answer(t("search_empty", u[5]))
    msg = "<b>🔎 Found:</b>\n\n" + "\n".join([f"🔹 {n[0]}" for n in res])
    await m.answer(msg, parse_mode="HTML")

@router.message(F.text.in_({"📅 Створити нагадування", "📅 New Reminder"}))
async def start_creation(m: types.Message, state: FSMContext):
    if await is_banned(m.from_user.id): return
    await m.answer("✍️ Text:", parse_mode="Markdown")
    await state.set_state(ReminderFSM.waiting_for_text)

@router.message(StateFilter(ReminderFSM.waiting_for_text))
async def step_text_saved(m: types.Message, state: FSMContext):
    await state.update_data(remind_text=m.text)
    calendar = SimpleCalendar()
    await m.answer("📅 Date:", reply_markup=await calendar.start_calendar())
    await state.set_state(ReminderFSM.waiting_for_date)

@router.callback_query(SimpleCalendarCallback.filter(), StateFilter(ReminderFSM.waiting_for_date))
async def process_calendar(callback: types.CallbackQuery, callback_data: dict, state: FSMContext):
    calendar = SimpleCalendar()
    selected, date = await calendar.process_selection(callback, callback_data)
    if selected:
        formatted_date = date.strftime("%Y-%m-%d")
        await state.update_data(remind_date=formatted_date)
        await callback.message.edit_text(f"📅 {formatted_date}\n⏰ Time (HH:MM):", reply_markup=get_time_kb())
        await state.set_state(ReminderFSM.waiting_for_time)

@router.callback_query(F.data.startswith("time_"), StateFilter(ReminderFSM.waiting_for_time))
async def process_time_btn(callback: types.CallbackQuery, state: FSMContext):
    time_val = callback.data.split("_")[1]
    await finalize_reminder(callback.message, time_val, state, callback.from_user.id)
    await callback.answer()

@router.message(StateFilter(ReminderFSM.waiting_for_time))
async def process_time_text(m: types.Message, state: FSMContext):
    clean_time = normalize_time(m.text)
    u = await Database.get_user(m.from_user.id)
    if not clean_time:
        return await m.answer(t("error_format", u[5]))
    await finalize_reminder(m, clean_time, state, m.from_user.id)

async def finalize_reminder(message: types.Message, time_str: str, state: FSMContext, user_id: int):
    data = await state.get_data()
    u = await Database.get_user(user_id)
    full_datetime = f"{data['remind_date']} {time_str}:00"
    await Database.add_reminder(user_id, message.chat.id, data['remind_text'], full_datetime, recurrence=None)
    await message.answer(f"{t('rem_created', u[5])}\n📌 {data['remind_text']}\n⏰ {full_datetime}", parse_mode="HTML", reply_markup=await get_kb(user_id))
    await state.clear()

@router.message(F.text.in_({"📋 Список планів", "📋 My Plans"}))
async def show_list(m: types.Message):
    if await is_banned(m.from_user.id): return
    u = await Database.get_user(m.from_user.id)
    rows = await Database.get_active_reminders(m.from_user.id)
    if not rows: return await m.answer(t("rem_list_empty", u[5]))
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    await m.answer(f"📋 **{t('btn_list_rem', u[5])}:**", parse_mode="Markdown")
    
    for r in rows:
        rid, r_time, r_text = r
        r_date = r_time.split(" ")[0]
        r_clock = r_time.split(" ")[1][:5]
        date_info = f"Today {r_clock}" if r_date == today_str else f"{r_date} {r_clock}"
        
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✏️ Edit", callback_data=f"edit_{rid}"),
            InlineKeyboardButton(text="❌ Del", callback_data=f"del_{rid}")
        ]])
        await m.answer(f"📝 *{r_text}*\n⏰ {date_info}", parse_mode="Markdown", reply_markup=kb)

# --- РЕДАГУВАННЯ (загальна частина) ---
@router.callback_query(F.data.startswith("edit_"))
async def edit_start(call: types.CallbackQuery, state: FSMContext):
    rid = call.data.split("_")[1]
    await state.update_data(edit_id=rid)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Text", callback_data="edopt_text")],
        [InlineKeyboardButton(text="⏰ Time", callback_data="edopt_time")],
        [InlineKeyboardButton(text="🔙 Cancel", callback_data="edopt_cancel")]
    ])
    await call.message.answer("Edit what?", reply_markup=kb)
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
        await call.message.edit_text("New text:")
        await state.set_state(EditFSM.editing_text)
    elif action == "time":
        calendar = SimpleCalendar()
        await call.message.edit_text("New date:", reply_markup=await calendar.start_calendar())
        await state.set_state(EditFSM.editing_date)

@router.message(StateFilter(EditFSM.editing_text))
async def save_new_text(m: types.Message, state: FSMContext):
    data = await state.get_data()
    await Database.update_reminder_field(data['edit_id'], "remind_text", m.text)
    await m.answer("✅ Updated!", reply_markup=await get_kb(m.from_user.id))
    await state.clear()

@router.callback_query(SimpleCalendarCallback.filter(), StateFilter(EditFSM.editing_date))
async def edit_date_process(callback: types.CallbackQuery, callback_data: dict, state: FSMContext):
    calendar = SimpleCalendar()
    selected, date = await calendar.process_selection(callback, callback_data)
    if selected:
        await state.update_data(new_date=date.strftime("%Y-%m-%d"))
        await callback.message.edit_text("New time:", reply_markup=get_time_kb())
        await state.set_state(EditFSM.editing_time)

@router.callback_query(F.data.startswith("time_"), StateFilter(EditFSM.editing_time))
async def edit_time_btn(callback: types.CallbackQuery, state: FSMContext):
    time_val = callback.data.split("_")[1]
    await save_new_time(callback.message, time_val, state)

@router.message(StateFilter(EditFSM.editing_time))
async def edit_time_text(m: types.Message, state: FSMContext):
    clean_time = normalize_time(m.text)
    if not clean_time:
        return await m.answer("⚠️ Format error.")
    await save_new_time(m, clean_time, state)

async def save_new_time(message, time_val, state):
    data = await state.get_data()
    full_dt = f"{data['new_date']} {time_val}:00"
    await Database.update_reminder_field(data['edit_id'], "remind_time", full_dt)
    await message.answer(f"✅ {full_dt}", reply_markup=await get_kb(message.chat.id))
    await state.clear()

@router.callback_query(F.data.startswith("del_"))
async def del_rem(call: types.CallbackQuery):
    rid = call.data.split("_")[1]
    await Database.delete_reminder(rid)
    await call.message.delete()
    await call.answer("Deleted")

# --- ІНШІ ХЕНДЛЕРИ (ГОЛОС, ФОТО, ТЕКСТ) ---

@router.message(F.voice)
async def voice_handler(m: types.Message):
    if await is_banned(m.from_user.id): return
    file = await m.bot.get_file(m.voice.file_id)
    path = f"voice_{m.from_user.id}.ogg"
    await m.bot.download_file(file.file_path, path)
    u = await Database.get_user(m.from_user.id)
    text = await groq_transcribe(path, u[5])
    if os.path.exists(path): os.remove(path)
    await m.reply(f"🗣 {text}")
    await process_smart(m, text)

@router.message(F.photo)
async def photo_handler(m: types.Message):
    if await is_banned(m.from_user.id): return
    file = await m.bot.get_file(m.photo[-1].file_id)
    path = f"photo_{m.from_user.id}.jpg"
    await m.bot.download_file(file.file_path, path)
    u = await Database.get_user(m.from_user.id)
    ans = await groq_analyze_image(m.caption or "Describe", path, u[0], u[5])
    if os.path.exists(path): os.remove(path)
    await m.reply(ans)

@router.message(F.location)
async def location_handler(m: types.Message):
    await Database.update_user(m.from_user.id, lat=m.location.latitude, lon=m.location.longitude)
    await m.answer("📍 OK.")

@router.message(F.text)
async def text_handler(m: types.Message):
    ignored = ["📋 Список планів", "📋 My Plans", "📍 Погода", "📍 Weather", 
               "📅 Створити нагадування", "📅 New Reminder", "⚙️ Налаштування", "⚙️ Settings"]
    if m.text in ignored: return
    if m.text.startswith("/"): return
    if await is_banned(m.from_user.id):
        await m.answer(t("banned", "uk"))
        return

    await process_smart(m, m.text)

async def process_smart(m, text):
    u = await Database.get_user(m.from_user.id)
    # u[0]=toxic, u[1]=lat, u[2]=lon, u[5]=lang
    res = await groq_text_brain(text, m.from_user.id, u[0], u[1], u[2], u[5], bool(m.forward_origin))
    
    if res:
        reply = res.get('reply', '...')
        await Database.add_to_context(m.from_user.id, "user", m.text)
        await Database.add_to_context(m.from_user.id, "assistant", reply)
        
        if res.get('save_note'):
            await Database.add_note(m.from_user.id, res['save_note'])
            reply += f"\n\n{t('saved_note', u[5])}"

        if res.get('is_reminder') and res.get('time'):
            await Database.add_reminder(m.from_user.id, m.chat.id, res['task'], res['time'], res['recurrence'])
            reply += f"\n⏰ {res['time']}"

        await m.answer(reply)

@router.error()
async def error_handler(event: ErrorEvent):
    logger.error(f"Critical Error: {event.exception}", exc_info=True)
