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
        spam_cutoff = (now - timedelta(seconds=60)).strftime("%Y-%m-%d %H:%M:%S")

        async with aiosqlite.connect(DB_NAME, timeout=30) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            query = """SELECT id, chat_id, remind_text, user_id, status, recurrence, remind_time, last_spam_sent_at
                       FROM reminders
                       WHERE (status='pending' AND remind_time <= ?)
                          OR (status='spamming' AND (last_spam_sent_at IS NULL OR last_spam_sent_at <= ?))"""
            async with db.execute(query, (now_str, spam_cutoff)) as c:
                rows = await c.fetchall()

        for r in rows:
            rid, chat_id, text, user_id, status, recurrence, r_time, _ = r
            user = await Database.get_user(user_id)
            is_toxic, spam_mode, lang, is_banned = user[0], user[4], user[5], user[7]
            if is_banned:
                continue

            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t("done_btn", lang), callback_data=f"confirm_{rid}")]])

            if spam_mode:
                msg = f"🤬 РОБИ ДАВАЙ: {text}" if is_toxic else f"{t('rem_prefix', lang)} {text}"
                try:
                    await bot.send_message(chat_id, msg, reply_markup=kb)
                except Exception as e:
                    logger.error(f"Send error: {e}")
                    continue

                async with aiosqlite.connect(DB_NAME, timeout=30) as db:
                    await db.execute("PRAGMA busy_timeout=5000")
                    if status == 'pending':
                        await db.execute(
                            "UPDATE reminders SET status='spamming', last_spam_sent_at=? WHERE id=?",
                            (now_str, rid)
                        )
                    else:
                        await db.execute("UPDATE reminders SET last_spam_sent_at=? WHERE id=?", (now_str, rid))
                    await db.commit()
                continue

            try:
                await bot.send_message(chat_id, f"{t('rem_prefix', lang)} {text}")
            except Exception as e:
                logger.error(f"Send error: {e}")
                continue

            async with aiosqlite.connect(DB_NAME, timeout=30) as db:
                await db.execute("PRAGMA busy_timeout=5000")
                if recurrence == 'daily':
                    try:
                        old_time = datetime.strptime(r_time, "%Y-%m-%d %H:%M:%S")
                        new_time = (old_time + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
                        await db.execute(
                            "UPDATE reminders SET remind_time=?, status='pending', last_spam_sent_at=NULL WHERE id=?",
                            (new_time, rid)
                        )
                    except Exception:
                        await db.execute("UPDATE reminders SET status='fired', last_spam_sent_at=NULL WHERE id=?", (rid,))
                else:
                    await db.execute("UPDATE reminders SET status='fired', last_spam_sent_at=NULL WHERE id=?", (rid,))
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
        
        async with aiosqlite.connect(DB_NAME, timeout=30) as db:
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
