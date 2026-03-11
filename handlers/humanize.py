from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from states import OrderStates
from config import MIN_WORDS, MIN_ORDER_AMOUNT, MAX_WORDS, KASPI_NUMBER, KASPI_NAME, PAYMENT_TIMEOUT_MINUTES
from services.word_counter import count_words, calculate_price, format_price
from services.usage_tracker import can_process
from database.models import ensure_user, create_order

router = Router()


@router.message(F.text, ~F.text.startswith("/"))
async def handle_text(message: Message, state: FSMContext):
    current_state = await state.get_state()

    # If user is in the middle of a flow, redirect
    if current_state == OrderStates.awaiting_payment.state:
        await message.answer("Сейчас ожидается скриншот оплаты. Отправь фото чека или /cancel для отмены.")
        return
    if current_state == OrderStates.pending_approval.state:
        await message.answer("Твой заказ на проверке. Дождись подтверждения или /cancel для отмены.")
        return
    if current_state == OrderStates.processing.state:
        await message.answer("Текст обрабатывается. Подожди немного.")
        return

    # Handle confirmation in text_received state
    if current_state == OrderStates.text_received.state:
        text_lower = message.text.strip().lower()
        if text_lower in ("да", "yes", "ок", "ok"):
            return await confirm_order(message, state)
        elif text_lower in ("отмена", "нет", "cancel", "no"):
            await state.clear()
            await message.answer("Отменено. Можешь отправить новый текст.")
            return
        else:
            await message.answer('Отправь "Да" чтобы продолжить или "Отмена" чтобы отказаться.')
            return

    # New text — process it
    await ensure_user(message.from_user.id, message.from_user.username, message.from_user.first_name)

    text = message.text.strip()
    words = count_words(text)

    if words < MIN_WORDS:
        await message.answer(
            f"Минимальный заказ — {MIN_ORDER_AMOUNT} ₸ ({MIN_WORDS} слов).\n"
            f"В твоём тексте — {words}. Отправь текст побольше."
        )
        return

    if words > MAX_WORDS:
        await message.answer(
            f"Максимум {MAX_WORDS} слов за раз. В твоём тексте — {words}.\n"
            "Раздели текст на части и отправь по отдельности."
        )
        return

    if not await can_process(words):
        await message.answer("К сожалению, лимит на этот месяц исчерпан. Попробуй в начале следующего месяца.")
        return

    price = calculate_price(words)

    await state.set_state(OrderStates.text_received)
    await state.update_data(text=text, word_count=words, price=price)

    await message.answer(
        f"<b>Слов в тексте:</b> {words:,}\n"
        f"<b>Стоимость:</b> {format_price(price)} ₸\n"
        "\n"
        "——————————————————\n"
        'Отправь "Да" чтобы продолжить или "Отмена" чтобы отказаться.',
        parse_mode="HTML",
    )


async def confirm_order(message: Message, state: FSMContext):
    data = await state.get_data()
    price = data["price"]

    order_id = await create_order(
        user_id=message.from_user.id,
        text=data["text"],
        word_count=data["word_count"],
        price=price,
    )

    await state.set_state(OrderStates.awaiting_payment)
    await state.update_data(order_id=order_id)

    await message.answer(
        f"Переведи <b>{format_price(price)} ₸</b> на Каспи:\n"
        f"<code>{KASPI_NUMBER}</code>  ({KASPI_NAME})\n"
        "\n"
        "После оплаты отправь скриншот чека сюда.\n"
        f"На оплату — {PAYMENT_TIMEOUT_MINUTES} минут.",
        parse_mode="HTML",
    )
