import pytz
import asyncio
import aiosqlite
import os
import random
from datetime import datetime, timedelta
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from config import TIMEZONE, DB_NAME, logger, RETENTION_DAYS, ADMIN_IDS
from database import Database
from utils import create_backup, get_weather
from locales import t

async def checker(bot: Bot):
    try:
        now = datetime.now(pytz.timezone(TIMEZONE))
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        
        async with aiosqlite.connect(DB_NAME) as db:
            query = """SELECT id, chat_id, remind_text, user_id, status, recurrence, remind_time 
                       FROM reminders WHERE (status='pending' AND remind_time <= ?) OR status='spamming'"""
            async with db.execute(query, (now_str,)) as c:
                rows = await c.fetchall()
                
            for r in rows:
                rid, chat_id, text, user_id, status, recurrence, r_time = r
                user = await Database.get_user(user_id)
                # user: 0=toxic, 4=spam, 5=lang, 6=morning, 7=banned
                is_toxic, spam_mode, is_banned = user[0], user[4], user[7]
                
                if is_banned: continue 

                kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Done", callback_data=f"confirm_{rid}")]])
                
                if spam_mode:
                    if status == 'pending':
                        await db.execute("UPDATE reminders SET status='spamming' WHERE id=?", (rid,))
                    msg = f"🤬 РОБИ ДАВАЙ: {text}" if is_toxic else f"🔔 Reminder: {text}"
                    try: await bot.send_message(chat_id, msg, reply_markup=kb)
                    except Exception as e: logger.error(f"Send error: {e}")
                
                else:
                    if status == 'pending':
                        prefix = "🔔" 
                        try: await bot.send_message(chat_id, f"{prefix} {text}")
                        except: pass
                        
                        if recurrence == 'daily':
                            try:
                                old_time = datetime.strptime(r_time, "%Y-%m-%d %H:%M:%S")
                                new_time = (old_time + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
                                await db.execute("UPDATE reminders SET remind_time=?, status='pending' WHERE id=?", (new_time, rid))
                            except:
                                await db.execute("UPDATE reminders SET status='fired' WHERE id=?", (rid,))
                        else:
                            await db.execute("UPDATE reminders SET status='fired' WHERE id=?", (rid,))
            
            await db.commit()
    except Exception as e:
        logger.error(f"Task error: {e}")

async def daily_morning_briefing(bot: Bot):
    """Розсилає ранкове повідомлення тим, у кого воно включено"""
    users = await Database.get_all_users() # (user_id, is_toxic, lat, lon, spam_mode, language, morning_briefing)
    
    for user_data in users:
        user_id = user_data[0]
        lang = user_data[5]
        morning_enabled = user_data[6]
        
        # Перевірка налаштування
        if not morning_enabled: continue

        lat, lon = user_data[2], user_data[3]
        
        w_text = ""
        if lat and lon:
            w = await get_weather(lat, lon)
            if w:
                w_text = f"{t('morning_weather', lang)} {w['temp']}°C, ☔ {w['rain']}%\n"
        
        async with aiosqlite.connect(DB_NAME) as db:
            now = datetime.now(pytz.timezone(TIMEZONE))
            today_start = now.strftime("%Y-%m-%d 00:00:00")
            today_end = now.strftime("%Y-%m-%d 23:59:59")
            query = "SELECT remind_text, remind_time FROM reminders WHERE user_id=? AND remind_time BETWEEN ? AND ? AND status='pending'"
            async with db.execute(query, (user_id, today_start, today_end)) as c:
                plans = await c.fetchall()
        
        plans_text = ""
        if plans:
            plans_text = t("morning_plans", lang)
            for p in plans:
                time_only = p[1].split(" ")[1][:5]
                plans_text += f"▫️ {time_only} - {p[0]}\n"
        else:
            plans_text = t("morning_no_plans", lang)

        notes = await Database.get_recent_notes(user_id, limit=20)
        quote_text = ""
        if notes:
            random_note = random.choice(notes)
            if len(random_note) > 10:
                quote_text = f"\n{t('morning_quote', lang)}<i>\"{random_note[:100]}...\"</i>"

        msg = f"{t('morning_title', lang)}{w_text}\n{plans_text}{quote_text}"
        
        try:
            await bot.send_message(user_id, msg, parse_mode="HTML")
            await asyncio.sleep(0.1)
        except: pass

async def background_maintenance(bot: Bot):
    days_counter = 0
    while True:
        try:
            await Database.clean_old_data(days=RETENTION_DAYS)
            if days_counter % 7 == 0 and ADMIN_IDS:
                backup_path = await create_backup()
                if backup_path:
                    try:
                        await bot.send_document(ADMIN_IDS[0], FSInputFile(backup_path), caption="📦 Auto Backup")
                        os.remove(backup_path)
                    except: pass
            days_counter += 1
            await asyncio.sleep(86400)
        except Exception as e:
            logger.error(f"Maintenance error: {e}")
            await asyncio.sleep(3600)
