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
from tasks import checker, background_maintenance, daily_morning_briefing

async def set_commands(bot: Bot):
    """Реєстрація команд для різних мов"""
    
    # --- УКРАЇНСЬКІ КОМАНДИ ---
    user_commands_uk = [
        BotCommand(command="start", description="🚀 Перезапуск бота"),
        BotCommand(command="settings", description="⚙️ Налаштування (Мова, Режими)"),
        BotCommand(command="note", description="📝 Додати нотатку"),
        BotCommand(command="search", description="🔍 Пошук у нотатках"),
        BotCommand(command="report", description="🆘 Написати адміну"),
        BotCommand(command="ping", description="🩺 Перевірка стану бота"),
    ]
    
    admin_commands_uk = user_commands_uk + [
        BotCommand(command="cancel", description="🛑 Скасувати поточну дію"),
        BotCommand(command="stats", description="📊 Статистика сервера"),
        BotCommand(command="db_status", description="🗄 Статус reminders БД"),
        BotCommand(command="users", description="👥 Список користувачів"),
        BotCommand(command="ban", description="🚫 Забанити (ID)"),
        BotCommand(command="unban", description="🕊 Розбанити (ID)"),
        BotCommand(command="broadcast", description="📢 Розсилка всім"),
        BotCommand(command="backup", description="📦 Скачати базу даних"),
        BotCommand(command="all_reminders", description="⏳ Всі активні нагадування"),
        BotCommand(command="all_notes", description="🕵️ Останні нотатки"),
        BotCommand(command="db_clean", description="🧹 Очистити старі дані"),
        BotCommand(command="restart", description="🔄 Перезавантажити бота")
    ]

    # --- ENGLISH COMMANDS ---
    user_commands_en = [
        BotCommand(command="start", description="🚀 Restart bot"),
        BotCommand(command="settings", description="⚙️ Settings (Lang, Modes)"),
        BotCommand(command="note", description="📝 Add note"),
        BotCommand(command="search", description="🔍 Search notes"),
        BotCommand(command="report", description="🆘 Contact support"),
        BotCommand(command="ping", description="🩺 Bot health check"),
    ]

    admin_commands_en = user_commands_en + [
        BotCommand(command="cancel", description="🛑 Cancel current action"),
        BotCommand(command="stats", description="📊 Server Stats"),
        BotCommand(command="db_status", description="🗄 Reminders DB status"),
        BotCommand(command="users", description="👥 User List"),
        BotCommand(command="ban", description="🚫 Ban User (ID)"),
        BotCommand(command="unban", description="🕊 Unban User (ID)"),
        BotCommand(command="broadcast", description="📢 Broadcast message"),
        BotCommand(command="backup", description="📦 Download Database"),
        BotCommand(command="all_reminders", description="⏳ All active reminders"),
        BotCommand(command="all_notes", description="🕵️ Recent notes"),
        BotCommand(command="db_clean", description="🧹 Clean old data"),
        BotCommand(command="restart", description="🔄 Restart Bot")
    ]

    # 1. Встановлюємо дефолтні команди (англійська як база)
    await bot.set_my_commands(user_commands_en, scope=BotCommandScopeDefault())
    
    # 2. Встановлюємо спеціально для української мови (language_code='uk')
    await bot.set_my_commands(user_commands_uk, scope=BotCommandScopeDefault(), language_code='uk')

    # 3. Встановлюємо адмінські команди для кожного адміна
    for admin_id in ADMIN_IDS:
        try:
            # Для адміна ставимо повний список (можна спробувати визначити мову, але зазвичай адміни знають укр)
            # Ставимо український варіант як пріоритет для адмінів
            await bot.set_my_commands(admin_commands_uk, scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception as e:
            logger.error(f"Failed to set commands for admin {admin_id}: {e}")

async def main():
    file_handler = RotatingFileHandler("bot.log", maxBytes=5*1024*1024, backupCount=2, encoding='utf-8')
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    file_handler.setFormatter(formatter)
    
    root = logging.getLogger()
    root.addHandler(file_handler)
    root.setLevel(logging.INFO)

    await Database.init()
    
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
    dp = Dispatcher()
    dp.include_router(router)
    
    # Реєструємо команди
    await set_commands(bot)
    
    scheduler = AsyncIOScheduler()
    scheduler.add_job(checker, 'interval', seconds=30, args=[bot], max_instances=1, coalesce=True)
    # Ранковий бріфінг щодня о 08:00
    scheduler.add_job(daily_morning_briefing, 'cron', hour=8, minute=0, args=[bot])
    scheduler.start()
    
    asyncio.create_task(background_maintenance(bot))
    
    logger.info("🤖 Бот запущено успішно!")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот зупинився.")
