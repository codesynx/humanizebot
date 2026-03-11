from config import PRICE_PER_WORD


def count_words(text: str) -> int:
    return len(text.split())


def calculate_price(word_count: int) -> float:
    return round(word_count * PRICE_PER_WORD, 2)


def format_price(price: float) -> str:
    if price == int(price):
        return f"{int(price)}"
    return f"{price:,.2f}".replace(",", " ")
