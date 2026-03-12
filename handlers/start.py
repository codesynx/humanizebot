from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from database.models import ensure_user, get_user_orders, get_user_summary
from services.word_counter import format_price

router = Router()

WELCOME_TEXT = (
    "Привет! Это <b>HumanizeKZ</b>\n"
    "Бот для humanize текстов. Без подписок — платишь только за то, что используешь.\n"
    "\n"
    "<b>Как это работает:</b>\n"
    "\n"
    "1. Отправь текст\n"
    "2. Бот посчитает слова и покажет цену\n"
    "3. Оплати на Каспи → скинь скрин\n"
    "4. Получи обработанный текст\n"
    "\n"
    "——————————————————\n"
    "<b>Цена: 0.75 ₸ за слово</b>\n"
    "500 слов → 375 ₸\n"
    "1000 слов → 750 ₸\n"
    "2000 слов → 1500 ₸\n"
    "——————————————————\n"
    "\n"
    "Просто отправь текст, чтобы начать."
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await ensure_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await message.answer(WELCOME_TEXT, parse_mode="HTML")


@router.message(Command("help"))
async def cmd_help(message: Message):
    text = (
        "<b>HumanizeKZ</b> — humanize текстов по цене 0.75 ₸/слово.\n"
        "\n"
        "<b>Команды:</b>\n"
        "/start — начать сначала\n"
        "/cancel — отменить текущий заказ\n"
        "/help — справка\n"
        "\n"
        "Отправь текст от 134 до 5 000 слов — бот рассчитает стоимость."
    )
    await message.answer(text, parse_mode="HTML")


@router.message(Command("myorders"))
async def cmd_myorders(message: Message):
    summary = await get_user_summary(message.from_user.id)
    orders = await get_user_orders(message.from_user.id, limit=10)

    if not orders:
        await message.answer("У тебя пока нет заказов. Отправь текст, чтобы начать.")
        return

    status_labels = {
        "pending": "ожидание",
        "paid": "оплачен",
        "completed": "выполнен",
        "rejected": "отклонён",
        "expired": "истёк",
    }

    lines = [
        f"<b>Всего слов:</b> {summary['total_words_used']:,}",
        f"<b>Всего оплачено:</b> {format_price(summary['total_paid'])} ₸",
        "",
        "<b>Последние заказы:</b>",
    ]

    for o in orders:
        status = status_labels.get(o["status"], o["status"])
        date = o["created_at"][:10] if o["created_at"] else "—"
        lines.append(
            f"  #{o['id']}  {o['word_count']:,} слов  "
            f"{format_price(o['price'])} ₸  [{status}]  {date}"
        )

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    # Also reset admin update flow if active
    from handlers.admin import _reset_admin_update
    _reset_admin_update()
    await message.answer("Отменено. Можешь отправить новый текст.")
