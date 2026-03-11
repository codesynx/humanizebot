from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from database.models import ensure_user

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


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    # Also reset admin update flow if active
    from handlers.admin import _reset_admin_update
    _reset_admin_update()
    await message.answer("Отменено. Можешь отправить новый текст.")
