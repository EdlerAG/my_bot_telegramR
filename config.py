import os
import sys
import logging
from dotenv import load_dotenv

# Завантажуємо .env
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
GROQ_KEY = os.getenv("GROQ_API_KEY")
ADMIN_ID = os.getenv("ADMIN_ID")
TIMEZONE = os.getenv("TIMEZONE", "Europe/Kyiv")
DB_NAME = "jarvis_db.db"

# Перевірка
if not TOKEN or not GROQ_KEY:
    sys.exit("❌ ПОМИЛКА: Немає ключів у файлі .env!")

# Налаштування логування
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("JarvisBot")
