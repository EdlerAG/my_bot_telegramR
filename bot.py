import asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import TOKEN, logger
from database import Database
from handlers import router
from tasks import checker

async def main():
    # Ініціалізація БД
    await Database.init()
    
    # Ініціалізація Бота
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
    dp = Dispatcher()
    
    # Підключаємо роутери
    dp.include_router(router)
    
    # Запускаємо планувальник і передаємо туди бота!
    scheduler = AsyncIOScheduler()
    scheduler.add_job(checker, 'interval', seconds=30, args=[bot])
    scheduler.start()
    
    logger.info("🤖 Бот запущено!")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот зупинився.")
