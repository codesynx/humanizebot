import asyncio
import logging

from aiogram import Router, Bot, F
from aiogram.types import Message, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import StorageKey

from config import ADMIN_ID, BOT_TOKEN
from states import OrderStates
from database.models import get_order, update_order_status, update_user_stats, get_monthly_stats
from services.humanizer_api import humanize_text, HumanizerAPIError
from services.usage_tracker import add_usage, get_remaining_words, set_personal_words
from services.word_counter import format_price

logger = logging.getLogger(__name__)

router = Router()


def is_admin(message: Message) -> bool:
    return message.from_user.id == ADMIN_ID


@router.message(F.text.regexp(r"^/approve_(\d+)$"))
async def cmd_approve(message: Message, bot: Bot, fsm_storage: MemoryStorage):
    if not is_admin(message):
        return

    order_id = int(message.text.split("_")[1])
    order = await get_order(order_id)

    if order is None:
        await message.answer(f"Заказ #{order_id} не найден.")
        return

    if order["status"] not in ("pending", "paid"):
        await message.answer(f"Заказ #{order_id} уже обработан (статус: {order['status']}).")
        return

    user_id = order["user_id"]

    # Notify user that processing started
    await bot.send_message(user_id, "Оплата подтверждена. Обрабатываю текст, подожди...")

    # Get text from FSM storage
    storage = fsm_storage
    key = StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id)
    data = await storage.get_data(key)
    text = data.get("text", "")

    if not text:
        await message.answer(f"Текст заказа #{order_id} не найден в хранилище. Возможно, сессия истекла.")
        await bot.send_message(user_id, "Произошла ошибка — текст не найден. Свяжись с администратором.")
        await update_order_status(order_id, "rejected")
        await storage.set_state(key, None)
        return

    # Set processing state
    await storage.set_state(key, OrderStates.processing.state)

    # Keep "typing..." indicator alive while API processes
    typing_active = True

    async def keep_typing():
        while typing_active:
            try:
                await bot.send_chat_action(user_id, "typing")
            except Exception:
                pass
            await asyncio.sleep(4)

    typing_task = asyncio.create_task(keep_typing())

    try:
        result = await humanize_text(text)
    except HumanizerAPIError as e:
        typing_active = False
        typing_task.cancel()
        logger.error("Humanizer API error for order #%d: %s", order_id, e)
        await bot.send_message(
            user_id,
            "Произошла ошибка при обработке текста. Мы разберёмся — деньги будут возвращены.",
        )
        await message.answer(f"API ошибка для заказа #{order_id}: {e}")
        await update_order_status(order_id, "rejected")
        await storage.set_state(key, None)
        await storage.set_data(key, {})
        return
    finally:
        typing_active = False
        typing_task.cancel()

    # Send result
    if len(result) <= 4096:
        await bot.send_message(user_id, result)
    else:
        file = BufferedInputFile(
            result.encode("utf-8"),
            filename=f"humanized_{order_id}.txt",
        )
        await bot.send_document(user_id, document=file, caption="Готово — результат в файле.")

    # Update stats
    word_count = order["word_count"]
    price = order["price"]
    await update_order_status(order_id, "completed")
    await update_user_stats(user_id, word_count, price)
    await add_usage(word_count)

    # Clear FSM
    await storage.set_state(key, None)
    await storage.set_data(key, {})

    await message.answer(f"Заказ #{order_id} выполнен. {word_count} слов обработано.")


@router.message(F.text.regexp(r"^/reject_(\d+)$"))
async def cmd_reject(message: Message, bot: Bot, fsm_storage: MemoryStorage):
    if not is_admin(message):
        return

    order_id = int(message.text.split("_")[1])
    order = await get_order(order_id)

    if order is None:
        await message.answer(f"Заказ #{order_id} не найден.")
        return

    if order["status"] not in ("pending", "paid"):
        await message.answer(f"Заказ #{order_id} уже обработан (статус: {order['status']}).")
        return

    user_id = order["user_id"]
    await update_order_status(order_id, "rejected")

    # Clear FSM
    storage = fsm_storage
    key = StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id)
    await storage.set_state(key, None)
    await storage.set_data(key, {})

    await bot.send_message(
        user_id,
        "Оплата не подтверждена. Если считаешь, что это ошибка — свяжись с администратором.",
    )
    await message.answer(f"Заказ #{order_id} отклонён.")


@router.message(F.text == "/stats")
async def cmd_stats(message: Message):
    if not is_admin(message):
        return

    stats = await get_monthly_stats()
    remaining = await get_remaining_words()

    await message.answer(
        f"<b>Статистика за текущий месяц</b>\n"
        f"——————————————————\n"
        f"Заказов выполнено: {stats['cnt']}\n"
        f"Заработано: {format_price(stats['revenue'])} ₸\n"
        f"Слов обработано: {stats['words']:,}\n"
        f"Осталось в лимите: {remaining:,}",
        parse_mode="HTML",
    )


@router.message(F.text == "/remaining")
async def cmd_remaining(message: Message):
    if not is_admin(message):
        return

    remaining = await get_remaining_words()
    await message.answer(f"Осталось слов в лимите: <b>{remaining:,}</b>", parse_mode="HTML")


@router.message(F.text.regexp(r"^/setpersonal\s+(\d+)$"))
async def cmd_set_personal(message: Message):
    if not is_admin(message):
        return

    count = int(message.text.split()[1])
    await set_personal_words(count)
    remaining = await get_remaining_words()
    await message.answer(
        f"Личный расход обновлён: {count:,} слов.\nОсталось в лимите: {remaining:,}",
    )
