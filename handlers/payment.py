from aiogram import Router, F, Bot
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.utils.text_decorations import html_decoration

from states import OrderStates
from config import ADMIN_ID
from database.models import update_order_status
from services.word_counter import format_price

router = Router()

PREVIEW_LENGTH = 300


def _text_preview(text: str) -> str:
    """First N chars of user text, escaped for HTML."""
    preview = text[:PREVIEW_LENGTH]
    if len(text) > PREVIEW_LENGTH:
        preview += "..."
    return html_decoration.quote(preview)


@router.message(OrderStates.awaiting_payment, F.photo | F.document)
async def handle_payment_screenshot(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    order_id = data["order_id"]
    word_count = data["word_count"]
    price = data["price"]
    text = data.get("text", "")

    await update_order_status(order_id, "paid")
    await state.set_state(OrderStates.pending_approval)

    username = f"@{message.from_user.username}" if message.from_user.username else "—"

    admin_text = (
        f"Новый заказ <b>#{order_id}</b>\n"
        f"Пользователь: {username} (ID: <code>{message.from_user.id}</code>)\n"
        f"Слов: {word_count:,}\n"
        f"Сумма: {format_price(price)} ₸\n"
        "\n"
        f"<b>Превью текста:</b>\n"
        f"<blockquote>{_text_preview(text)}</blockquote>\n"
        "\n"
        f"/approve_{order_id} — подтвердить\n"
        f"/reject_{order_id} — отклонить"
    )

    # Forward the screenshot to admin
    if message.photo:
        await bot.send_photo(
            ADMIN_ID,
            photo=message.photo[-1].file_id,
            caption=admin_text,
            parse_mode="HTML",
        )
    elif message.document:
        await bot.send_document(
            ADMIN_ID,
            document=message.document.file_id,
            caption=admin_text,
            parse_mode="HTML",
        )

    await message.answer("Скриншот получен. Ожидай подтверждения — обычно это несколько минут.")


@router.message(OrderStates.awaiting_payment)
async def awaiting_payment_invalid(message: Message):
    await message.answer("Отправь скриншот чека (фото или файл). Или /cancel для отмены.")
