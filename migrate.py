import sqlite3
import os

OLD_DB = "old_jarvis.db"
NEW_DB = "jarvis_db.db"

def migrate():
    if not os.path.exists(OLD_DB):
        print(f"❌ Стара база {OLD_DB} не знайдена!")
        return

    # Підключаємось до нової бази
    conn = sqlite3.connect(NEW_DB)
    cursor = conn.cursor()

    # Приєднуємо стару базу
    cursor.execute(f"ATTACH DATABASE '{OLD_DB}' AS old_db")

    print("🚀 Починаю міграцію даних...")

    try:
        # 1. Переносимо нагадування (структура ідентична)
        cursor.execute("INSERT INTO reminders (user_id, chat_id, remind_text, remind_time, recurrence, status) "
                       "SELECT user_id, chat_id, remind_text, remind_time, recurrence, status FROM old_db.reminders")
        print(f"✅ Нагадування перенесено: {cursor.rowcount}")

        # 2. Переносимо нотатки
        cursor.execute("INSERT INTO notes (user_id, content, created_at) "
                       "SELECT user_id, content, created_at FROM old_db.notes")
        print(f"✅ Нотатки перенесено: {cursor.rowcount}")

        # 3. Переносимо користувачів (враховуємо нові колонки)
        # Ми беремо старі дані, а нові (language, morning_briefing, is_banned) заповнюємо дефолтними значеннями
        cursor.execute("""
            INSERT OR IGNORE INTO users (user_id, is_toxic, spam_mode, lat, lon, language, morning_briefing, is_banned)
            SELECT user_id, is_toxic, spam_mode, lat, lon, 'uk', 1, 0 FROM old_db.users
        """)
        print(f"✅ Користувачів перенесено: {cursor.rowcount}")

        # 4. Переносимо контекст (історію діалогів)
        cursor.execute("INSERT INTO context (user_id, role, content, created_at) "
                       "SELECT user_id, role, content, created_at FROM old_db.context")
        print(f"✅ Контекст перенесено: {cursor.rowcount}")

        conn.commit()
        print("\n✨ Міграція успішно завершена! Тепер можна видаляти old_jarvis.db та запускати бота.")

    except Exception as e:
        print(f"💥 Помилка під час міграції: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
