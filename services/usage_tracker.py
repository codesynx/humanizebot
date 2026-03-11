from datetime import datetime, timezone

from database.db import get_db
from config import MONTHLY_WORD_LIMIT


def _current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


async def _ensure_month(month: str):
    db = await get_db()
    await db.execute(
        "INSERT OR IGNORE INTO monthly_usage (month, words_used, personal_words) VALUES (?, 0, 0)",
        (month,),
    )
    await db.commit()


async def get_remaining_words() -> int:
    month = _current_month()
    await _ensure_month(month)
    db = await get_db()
    cursor = await db.execute(
        "SELECT words_used, personal_words FROM monthly_usage WHERE month = ?",
        (month,),
    )
    row = await cursor.fetchone()
    used = row["words_used"] + row["personal_words"]
    return max(0, MONTHLY_WORD_LIMIT - used)


async def can_process(word_count: int) -> bool:
    remaining = await get_remaining_words()
    return remaining >= word_count


async def add_usage(word_count: int):
    month = _current_month()
    await _ensure_month(month)
    db = await get_db()
    await db.execute(
        "UPDATE monthly_usage SET words_used = words_used + ? WHERE month = ?",
        (word_count, month),
    )
    await db.commit()


async def set_personal_words(count: int):
    month = _current_month()
    await _ensure_month(month)
    db = await get_db()
    await db.execute(
        "UPDATE monthly_usage SET personal_words = ? WHERE month = ?",
        (count, month),
    )
    await db.commit()
