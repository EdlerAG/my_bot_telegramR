import os
import sys
import logging
from dotenv import load_dotenv

# Завантажуємо .env
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
GROQ_KEY = os.getenv("GROQ_API_KEY")
TIMEZONE = os.getenv("TIMEZONE", "Europe/Kyiv")
DB_NAME = "jarvis_db.db"

# Читаємо рядок і перетворюємо його на список чисел
admin_env = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(x) for x in admin_env.split(",")] if admin_env else []

# Скільки днів зберігати старі дані
RETENTION_DAYS = 7 

# Перевірка ключів
if not TOKEN or not GROQ_KEY:
    sys.exit("❌ ПОМИЛКА: Немає ключів у файлі .env!")

# Базове налаштування логування (буде розширене в bot.py)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("JarvisBot")
