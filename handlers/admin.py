import asyncio
import logging

from aiogram import Router, Bot, F
from aiogram.types import Message, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import StorageKey
from aiogram.utils.text_decorations import html_decoration

from config import ADMIN_ID, LOW_WORDS_THRESHOLD
from states import OrderStates
from database.models import get_order, update_order_status, update_user_stats, get_monthly_stats
from services.humanizer_api import humanize_text, HumanizerAPIError
from services.usage_tracker import (
    add_usage, get_remaining_words,
    set_bot_paused, is_bot_paused,
    set_remaining_from_api, get_word_limit,
)
from services.word_counter import format_price

logger = logging.getLogger(__name__)

router = Router()

# Simple flag for admin /update flow (no FSM needed — single admin)
_awaiting_word_update = False


def is_admin(message: Message) -> bool:
    return message.from_user.id == ADMIN_ID


def _reset_admin_update():
    global _awaiting_word_update
    _awaiting_word_update = False


async def _notify_admin_low_limit(bot: Bot):
    """Send a one-time alert when words remaining drops below threshold."""
    remaining = await get_remaining_words()
    if remaining <= LOW_WORDS_THRESHOLD and remaining > 0:
        await bot.send_message(
            ADMIN_ID,
            f"Осталось <b>{remaining:,}</b> слов в лимите.\n"
            f"Бот автоматически перешёл в режим тех. работ для новых заказов.",
            parse_mode="HTML",
        )


async def _send_error_report_to_admin(
    bot: Bot, order_id: int, user_id: int, username: str,
    word_count: int, price: float, text: str,
    screenshot_file_id: str | None, screenshot_type: str | None,
    error: str,
):
    """Send full order details to admin when API fails."""
    admin_text = (
        f"API ОШИБКА — заказ <b>#{order_id}</b>\n"
        f"——————————————————\n"
        f"Пользователь: {username} (ID: <code>{user_id}</code>)\n"
        f"Слов: {word_count:,}\n"
        f"Сумма: {format_price(price)} ₸\n"
        f"Ошибка: <code>{html_decoration.quote(str(error)[:200])}</code>\n"
        f"\n"
        f"Нужно вернуть деньги."
    )
    await bot.send_message(ADMIN_ID, admin_text, parse_mode="HTML")

    # Send the screenshot if available
    if screenshot_file_id:
        if screenshot_type == "photo":
            await bot.send_photo(ADMIN_ID, photo=screenshot_file_id, caption="Скриншот оплаты")
        else:
            await bot.send_document(ADMIN_ID, document=screenshot_file_id, caption="Скриншот оплаты")

    # Send full text as file
    text_file = BufferedInputFile(
        text.encode("utf-8"),
        filename=f"order_{order_id}_text.txt",
    )
    await bot.send_document(
        ADMIN_ID,
        document=text_file,
        caption=f"Полный текст заказа #{order_id} ({word_count:,} слов, {format_price(price)} ₸)",
    )


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
    screenshot_file_id = data.get("screenshot_file_id")
    screenshot_type = data.get("screenshot_type")

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

        # Send full error report to admin
        username = f"@{data.get('username', '?')}" if data.get("username") else f"ID:{user_id}"
        await _send_error_report_to_admin(
            bot, order_id, user_id, username,
            order["word_count"], order["price"], text,
            screenshot_file_id, screenshot_type, e,
        )

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

    # Check if limit is running low
    await _notify_admin_low_limit(bot)


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


@router.message(F.text == "/update")
async def cmd_update(message: Message):
    global _awaiting_word_update
    if not is_admin(message):
        return
    _awaiting_word_update = True
    remaining = await get_remaining_words()
    await message.answer(
        f"Сейчас в лимите: <b>{remaining:,}</b> слов.\n"
        "\n"
        "Введи количество слов, которое сейчас доступно на API.\n"
        "Или /cancel для отмены.",
        parse_mode="HTML",
    )


@router.message(F.text.regexp(r"^\d+$"))
async def handle_admin_number(message: Message):
    global _awaiting_word_update
    if not is_admin(message):
        return
    if not _awaiting_word_update:
        return

    _awaiting_word_update = False
    api_words = int(message.text.strip())

    result = await set_remaining_from_api(api_words)

    lines = [f"Лимит обновлён."]

    if result["extra_bought"] > 0:
        lines.append(
            f"Докуплено <b>+{result['extra_bought']:,}</b> слов."
        )

    lines.append(f"Доступно для бота: <b>{result['remaining']:,}</b> слов.")

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(F.text == "/pause")
async def cmd_pause(message: Message):
    if not is_admin(message):
        return
    await set_bot_paused(True)
    await message.answer("Бот приостановлен. Новые заказы не принимаются.\n/resume — возобновить.")


@router.message(F.text == "/resume")
async def cmd_resume(message: Message):
    if not is_admin(message):
        return
    await set_bot_paused(False)
    remaining = await get_remaining_words()
    await message.answer(f"Бот возобновлён. Осталось слов: {remaining:,}")


@router.message(F.text == "/stats")
async def cmd_stats(message: Message):
    if not is_admin(message):
        return

    stats = await get_monthly_stats()
    remaining = await get_remaining_words()
    word_limit = await get_word_limit()
    paused = await is_bot_paused()
    status = "приостановлен" if paused else "работает"

    await message.answer(
        f"<b>Статистика за текущий месяц</b>\n"
        f"——————————————————\n"
        f"Статус: {status}\n"
        f"Заказов выполнено: {stats['cnt']}\n"
        f"Заработано: {format_price(stats['revenue'])} ₸\n"
        f"Слов обработано: {stats['words']:,}\n"
        f"Лимит: {word_limit:,}\n"
        f"Осталось: {remaining:,}",
        parse_mode="HTML",
    )


@router.message(F.text == "/remaining")
async def cmd_remaining(message: Message):
    if not is_admin(message):
        return

    remaining = await get_remaining_words()
    await message.answer(f"Осталось слов в лимите: <b>{remaining:,}</b>", parse_mode="HTML")


