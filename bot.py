import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand

from config import BOT_TOKEN, PAYMENT_TIMEOUT_MINUTES
from database.db import get_db, close_db
from handlers import start, humanize, payment, admin

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def timeout_checker(bot: Bot, storage: MemoryStorage):
    """Background task: expire orders stuck in awaiting_payment / pending_approval."""
    while True:
        await asyncio.sleep(300)  # check every 5 minutes
        try:
            db = await get_db()
            cutoff = PAYMENT_TIMEOUT_MINUTES * 60
            cursor = await db.execute(
                "SELECT id, user_id, created_at FROM orders WHERE status IN ('pending', 'paid')"
            )
            rows = await cursor.fetchall()

            now = datetime.now(timezone.utc)
            for row in rows:
                created = datetime.fromisoformat(row["created_at"]).replace(tzinfo=timezone.utc)
                elapsed = (now - created).total_seconds()
                if elapsed > cutoff:
                    await db.execute(
                        "UPDATE orders SET status = 'expired' WHERE id = ?",
                        (row["id"],),
                    )
                    await db.commit()

                    from aiogram.fsm.storage.base import StorageKey
                    key = StorageKey(bot_id=bot.id, chat_id=row["user_id"], user_id=row["user_id"])
                    state = await storage.get_state(key)
                    if state is not None:
                        await storage.set_state(key, None)
                        await storage.set_data(key, {})

                    try:
                        await bot.send_message(
                            row["user_id"],
                            "Время на оплату истекло. Отправь текст заново, если хочешь повторить.",
                        )
                    except Exception:
                        pass

                    logger.info("Order #%d expired", row["id"])
        except Exception:
            logger.exception("Error in timeout checker")


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set. Check your .env file.")

    storage = MemoryStorage()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=None))
    dp = Dispatcher(storage=storage)
    dp["fsm_storage"] = storage

    dp.include_router(start.router)
    dp.include_router(admin.router)
    dp.include_router(payment.router)
    dp.include_router(humanize.router)

    # Init DB
    await get_db()

    # Set bot command menu (visible in Telegram's left menu)
    await bot.set_my_commands([
        BotCommand(command="start", description="Начать сначала"),
        BotCommand(command="myorders", description="Мои заказы"),
        BotCommand(command="help", description="Справка"),
        BotCommand(command="cancel", description="Отменить текущий заказ"),
    ])

    # Start timeout checker
    asyncio.create_task(timeout_checker(bot, storage))

    logger.info("Bot started")
    await dp.start_polling(bot)

    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
