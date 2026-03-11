from aiogram.fsm.state import State, StatesGroup


class OrderStates(StatesGroup):
    idle = State()
    text_received = State()
    awaiting_payment = State()
    pending_approval = State()
    processing = State()
