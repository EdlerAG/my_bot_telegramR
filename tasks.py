import pytz
import asyncio
import aiosqlite
from datetime import datetime, timedelta
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import TIMEZONE, DB_NAME, logger
from database import Database

async def checker(bot):
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
                # user[0]=is_toxic, user[4]=spam_mode
                is_toxic, spam_mode = user[0], user[4]

                if spam_mode:
                    if status == 'pending':
                        await db.execute("UPDATE reminders SET status='spamming' WHERE id=?", (rid,))
                    
                    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Зробив", callback_data=f"confirm_{rid}")]])
                    msg = f"🤬 РОБИ ДАВАЙ: {text}" if is_toxic else f"🔔 Нагадую: {text}"
                    try: await bot.send_message(chat_id, msg, reply_markup=kb)
                    except Exception as e: logger.error(f"Send error: {e}")
                
                else:
                    # Звичайний режим
                    if status == 'pending':
                        try: await bot.send_message(chat_id, f"🔔 Нагадування: {text}")
                        except: pass
                        
                        if recurrence:
                            # Проста логіка для повторень
                            await db.execute("UPDATE reminders SET status='fired' WHERE id=?", (rid,))
                        else:
                            await db.execute("UPDATE reminders SET status='fired' WHERE id=?", (rid,))
            
            await db.commit()
    except Exception as e:
        logger.error(f"Task error: {e}")
