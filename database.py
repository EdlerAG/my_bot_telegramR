import aiosqlite
import json
from datetime import datetime
from config import DB_NAME

class Database:
    @staticmethod
    async def init():
        async with aiosqlite.connect(DB_NAME) as db:
            # ОПТИМІЗАЦІЯ: Вмикаємо WAL-режим (швидше, надійніше)
            await db.execute("PRAGMA journal_mode=WAL;")
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, chat_id INTEGER, 
                    remind_text TEXT, remind_time TEXT, recurrence TEXT DEFAULT NULL, status TEXT DEFAULT 'pending'
                )""")
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY, is_toxic BOOLEAN DEFAULT 0, spam_mode BOOLEAN DEFAULT 0,
                    lat REAL DEFAULT NULL, lon REAL DEFAULT NULL, memory_json TEXT DEFAULT '[]'
                )""")
            # Таблиця для нотаток (Second Brain)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, content TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )""")
            # Таблиця для історії діалогу (Context)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS context (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, role TEXT, content TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )""")
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

    @staticmethod
    async def add_reminder(user_id, chat_id, text, time, recurrence):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("INSERT INTO reminders (user_id, chat_id, remind_text, remind_time, recurrence) VALUES (?,?,?,?,?)",
                             (user_id, chat_id, text, time, recurrence))
            await db.commit()

    # --- НОТАТКИ ---
    @staticmethod
    async def add_note(user_id, content):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("INSERT INTO notes (user_id, content) VALUES (?,?)", (user_id, content))
            await db.commit()

    @staticmethod
    async def search_notes(user_id, query):
        async with aiosqlite.connect(DB_NAME) as db:
            sql = "SELECT content, created_at FROM notes WHERE user_id = ? AND content LIKE ? ORDER BY id DESC LIMIT 10"
            async with db.execute(sql, (user_id, f"%{query}%")) as c:
                return await c.fetchall()

    @staticmethod
    async def get_recent_notes(user_id, limit=5):
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT content FROM notes WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit)) as c:
                return [row[0] for row in await c.fetchall()]

    # --- КОНТЕКСТ (ПАМ'ЯТЬ) ---
    @staticmethod
    async def add_to_context(user_id, role, content):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("INSERT INTO context (user_id, role, content) VALUES (?,?,?)", (user_id, role, content))
            # Тримаємо тільки останні 20 повідомлень
            await db.execute("DELETE FROM context WHERE id NOT IN (SELECT id FROM context WHERE user_id=? ORDER BY id DESC LIMIT 20) AND user_id=?", (user_id, user_id))
            await db.commit()

    @staticmethod
    async def get_context(user_id, limit=6):
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT role, content FROM context WHERE user_id=? ORDER BY id ASC LIMIT ?", (user_id, limit)) as c:
                return [{"role": r[0], "content": r[1]} for r in await c.fetchall()]

    # --- ФУНКЦІЇ ДЛЯ СПИСКУ ---
    @staticmethod
    async def get_active_reminders(user_id):
        async with aiosqlite.connect(DB_NAME) as db:
            query = "SELECT id, remind_time, remind_text FROM reminders WHERE user_id=? AND status IN ('pending','spamming') ORDER BY remind_time ASC"
            async with db.execute(query, (user_id,)) as c:
                return await c.fetchall()

    @staticmethod
    async def update_reminder_field(rem_id, field, value):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(f"UPDATE reminders SET {field}=? WHERE id=?", (value, rem_id))
            await db.commit()

    @staticmethod
    async def delete_reminder(rem_id):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("DELETE FROM reminders WHERE id=?", (rem_id,))
            await db.commit()

    # --- АДМІНКА ТА ОЧИЩЕННЯ ---
    @staticmethod
    async def get_stats():
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT COUNT(DISTINCT user_id) FROM users") as c:
                users = (await c.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM reminders WHERE status = 'pending'") as c:
                active_rems = (await c.fetchone())[0]
            return users, active_rems

    @staticmethod
    async def clean_old_data(days=7):
        async with aiosqlite.connect(DB_NAME) as db:
            if days > 0:
                await db.execute("DELETE FROM reminders WHERE status != 'pending' AND remind_time < datetime('now', ?)", (f'-{days} days',))
            else:
                # Повне очищення виконаних
                await db.execute("DELETE FROM reminders WHERE status != 'pending'")
            await db.commit()

    @staticmethod
    async def get_all_users():
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT user_id, is_toxic FROM users") as c:
                return await c.fetchall()

    @staticmethod
    async def get_all_active_reminders():
        async with aiosqlite.connect(DB_NAME) as db:
            sql = "SELECT id, user_id, remind_text, remind_time FROM reminders WHERE status = 'pending' ORDER BY remind_time ASC"
            async with db.execute(sql) as c:
                return await c.fetchall()

    @staticmethod
    async def get_latest_notes(limit=10):
        async with aiosqlite.connect(DB_NAME) as db:
            sql = "SELECT user_id, content, created_at FROM notes ORDER BY id DESC LIMIT ?"
            async with db.execute(sql, (limit,)) as c:
                return await c.fetchall()
