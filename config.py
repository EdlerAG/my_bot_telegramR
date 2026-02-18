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

# Читаємо рядок і перетворюємо його на список чисел (ігноруємо сміттєві значення)
admin_env = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = []
for raw_id in admin_env.split(","):
    raw_id = raw_id.strip()
    if not raw_id:
        continue
    if raw_id.isdigit():
        ADMIN_IDS.append(int(raw_id))

# Скільки днів зберігати старі дані
RETENTION_DAYS = 7 

# Перевірка ключів
if not TOKEN:
    sys.exit("❌ ПОМИЛКА: Немає BOT_TOKEN у файлі .env!")

# Базове налаштування логування (буде розширене в bot.py)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("JarvisBot")

if not GROQ_KEY:
    logger.warning("⚠️ GROQ_API_KEY відсутній. AI-функції (чат/голос/фото/YouTube summary) будуть вимкнені.")
