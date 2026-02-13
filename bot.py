import asyncio
import logging
from logging.handlers import RotatingFileHandler
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeDefault, BotCommandScopeChat
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import TOKEN, logger, ADMIN_IDS
from database import Database
from handlers import router
from tasks import checker, background_maintenance

async def set_commands(bot: Bot):
    """Меню команд"""
    user_commands = [
        BotCommand(command="start", description="Запуск"),
        BotCommand(command="note", description="Нотатка"),
        BotCommand(command="search", description="Пошук"),
        BotCommand(command="report", description="Повідомити про проблему")
    ]
    await bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())

    admin_commands = user_commands + [
        BotCommand(command="stats", description="📊 Статистика"),
        BotCommand(command="users", description="👥 Юзери"),
        BotCommand(command="backup", description="📦 Скачати бекап"),
        BotCommand(command="restart", description="🔄 Перезапуск"),
        BotCommand(command="broadcast", description="📢 Розсилка"),
        BotCommand(command="db_clean", description="🧹 Очистка")
    ]
    for admin_id in ADMIN_IDS:
        try:
            await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=admin_id))
        except: pass

async def main():
    # --- НАЛАШТУВАННЯ ЛОГУВАННЯ ---
    file_handler = RotatingFileHandler("bot.log", maxBytes=5*1024*1024, backupCount=2, encoding='utf-8')
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    file_handler.setFormatter(formatter)
    
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
    
    # Встановлюємо меню
    await set_commands(bot)
    
    # Запускаємо планувальник
    scheduler = AsyncIOScheduler()
    scheduler.add_job(checker, 'interval', seconds=30, args=[bot])
    scheduler.start()
    
    # Запускаємо фонову задачу (передаємо бота для бекапів)
    asyncio.create_task(background_maintenance(bot))
    
    logger.info("🤖 Бот запущено успішно!")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот зупинився.")
