import asyncio
import logging
from logging.handlers import RotatingFileHandler
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import TOKEN, logger
from database import Database
from handlers import router
from tasks import checker, background_maintenance

async def main():
    # --- НАЛАШТУВАННЯ ЛОГУВАННЯ ---
    # RotatingFileHandler: пише в bot.log, якщо файл > 5MB, архівує його (макс 2 архіви)
    file_handler = RotatingFileHandler("bot.log", maxBytes=5*1024*1024, backupCount=2, encoding='utf-8')
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    file_handler.setFormatter(formatter)
    
    # Додаємо хендлер до кореневого логера
    root = logging.getLogger()
    root.addHandler(file_handler)
    root.setLevel(logging.INFO)

    # Ініціалізація БД
    await Database.init()
    
    # Ініціалізація Бота
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
    dp = Dispatcher()
    
    # Підключаємо роутери
    dp.include_router(router)
    
    # Запускаємо планувальник нагадувань
    scheduler = AsyncIOScheduler()
    scheduler.add_job(checker, 'interval', seconds=30, args=[bot])
    scheduler.start()
    
    # Запускаємо задачу авто-очищення
    asyncio.create_task(background_maintenance())
    
    logger.info("🤖 Бот запущено успішно!")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот зупинився.")
