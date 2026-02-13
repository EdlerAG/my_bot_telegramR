import aiosqlite
import json
from config import DB_NAME

class Database:
    @staticmethod
    async def init():
        async with aiosqlite.connect(DB_NAME) as db:
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
            await db.execute("""
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, content TEXT, created_at TEXT
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

    @staticmethod
    async def add_note(user_id, content, created_at):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("INSERT INTO notes (user_id, content, created_at) VALUES (?,?,?)", (user_id, content, created_at))
            await db.commit()
