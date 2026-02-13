import pytz
import asyncio
import aiosqlite
import os
from datetime import datetime
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from config import TIMEZONE, DB_NAME, logger, RETENTION_DAYS, ADMIN_IDS
from database import Database
from utils import create_backup

async def checker(bot: Bot):
    """Фонова задача для перевірки нагадувань"""
    try:
        now = datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")
        
        async with aiosqlite.connect(DB_NAME) as db:
            query = """SELECT id, chat_id, remind_text, user_id, status, recurrence, remind_time 
                       FROM reminders WHERE (status='pending' AND remind_time <= ?) OR status='spamming'"""
            async with db.execute(query, (now,)) as c:
                rows = await c.fetchall()
                
            for r in rows:
                rid, chat_id, text, user_id, status, recurrence, r_time = r
                user = await Database.get_user(user_id)
                is_toxic, spam_mode = user[0], user[4]

                if spam_mode:
                    if status == 'pending':
                        await db.execute("UPDATE reminders SET status='spamming' WHERE id=?", (rid,))
                    
                    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Зробив", callback_data=f"confirm_{rid}")]])
                    msg = f"🤬 РОБИ ДАВАЙ: {text}" if is_toxic else f"🔔 Нагадую: {text}"
                    try: await bot.send_message(chat_id, msg, reply_markup=kb)
                    except Exception as e: logger.error(f"Send error: {e}")
                
                else:
                    if status == 'pending':
                        try: await bot.send_message(chat_id, f"🔔 Нагадування: {text}")
                        except: pass
                        if recurrence:
                            # Тут можна додати логіку повторень
                            await db.execute("UPDATE reminders SET status='fired' WHERE id=?", (rid,))
                        else:
                            await db.execute("UPDATE reminders SET status='fired' WHERE id=?", (rid,))
            
            await db.commit()
    except Exception as e:
        logger.error(f"Task error: {e}")

async def background_maintenance(bot: Bot):
    """Щоденне очищення та щотижневий бекап"""
    days_counter = 0
    while True:
        try:
            # Чистимо базу
            await Database.clean_old_data(days=RETENTION_DAYS)
            
            # Раз на 7 днів - бекап
            if days_counter % 7 == 0 and ADMIN_IDS:
                backup_path = await create_backup()
                if backup_path:
                    try:
                        await bot.send_document(ADMIN_IDS[0], FSInputFile(backup_path), caption="📦 Автоматичний бекап")
                        os.remove(backup_path)
                    except Exception as e:
                        logger.error(f"Failed to send backup: {e}")

            days_counter += 1
            await asyncio.sleep(86400) # Чекаємо добу
        except Exception as e:
            logger.error(f"Maintenance error: {e}")
            await asyncio.sleep(3600)
