import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
HUMANIZER_API_URL = "https://ai-text-humanizer.com/api.php"
HUMANIZER_EMAIL = os.getenv("HUMANIZER_EMAIL", "")
HUMANIZER_PASSWORD = os.getenv("HUMANIZER_PASSWORD", "")

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
KASPI_NUMBER = os.getenv("KASPI_NUMBER", "+7 XXX XXX XX XX")
KASPI_NAME = os.getenv("KASPI_NAME", "Имя Ф.")

PRICE_PER_WORD = 0.75
MIN_ORDER_AMOUNT = 100  # минимальный заказ в тенге
MIN_WORDS = 134  # ceil(MIN_ORDER_AMOUNT / PRICE_PER_WORD)
MAX_WORDS = 5000
MONTHLY_WORD_LIMIT = 50000
PAYMENT_TIMEOUT_MINUTES = 30

DB_PATH = "bot_data.db"
