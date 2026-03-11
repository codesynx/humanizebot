from datetime import datetime, timezone

from database.db import get_db
from config import MONTHLY_WORD_LIMIT, LOW_WORDS_THRESHOLD


def _current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


async def _ensure_month(month: str):
    db = await get_db()
    await db.execute(
        "INSERT OR IGNORE INTO monthly_usage (month, words_used, personal_words) VALUES (?, 0, 0)",
        (month,),
    )
    await db.commit()


async def _ensure_settings():
    db = await get_db()
    await db.execute(
        "CREATE TABLE IF NOT EXISTS bot_settings (key TEXT PRIMARY KEY, value TEXT)"
    )
    await db.commit()


async def _get_setting(key: str, default: str = "0") -> str:
    await _ensure_settings()
    db = await get_db()
    cursor = await db.execute("SELECT value FROM bot_settings WHERE key = ?", (key,))
    row = await cursor.fetchone()
    return row["value"] if row else default


async def _set_setting(key: str, value: str):
    await _ensure_settings()
    db = await get_db()
    await db.execute(
        "INSERT INTO bot_settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    await db.commit()


# --- Word limit (dynamic, stored in DB) ---

async def get_word_limit() -> int:
    val = await _get_setting("word_limit", str(MONTHLY_WORD_LIMIT))
    return int(val)


async def set_word_limit(limit: int):
    await _set_setting("word_limit", str(limit))


async def get_bot_words_used() -> int:
    """Words used by bot orders this month."""
    month = _current_month()
    await _ensure_month(month)
    db = await get_db()
    cursor = await db.execute(
        "SELECT words_used FROM monthly_usage WHERE month = ?", (month,)
    )
    row = await cursor.fetchone()
    return row["words_used"]


async def get_remaining_words() -> int:
    word_limit = await get_word_limit()
    bot_used = await get_bot_words_used()
    return max(0, word_limit - bot_used)


async def set_remaining_from_api(api_words: int) -> dict:
    """
    Admin says "I have X words on the API right now".
    Recalculate: new_limit = api_words + bot_words_used_this_month.
    Returns info about what changed.
    """
    old_limit = await get_word_limit()
    bot_used = await get_bot_words_used()
    new_limit = api_words + bot_used

    extra_bought = 0
    if new_limit > old_limit:
        extra_bought = new_limit - old_limit

    await set_word_limit(new_limit)

    return {
        "old_limit": old_limit,
        "new_limit": new_limit,
        "extra_bought": extra_bought,
        "remaining": api_words,
        "bot_used": bot_used,
    }


async def is_available() -> bool:
    """Check if bot can accept orders: not paused and enough words remaining."""
    if await is_bot_paused():
        return False
    remaining = await get_remaining_words()
    return remaining > LOW_WORDS_THRESHOLD


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


# --- Bot pause flag ---

async def is_bot_paused() -> bool:
    return (await _get_setting("paused", "0")) == "1"


async def set_bot_paused(paused: bool):
    await _set_setting("paused", "1" if paused else "0")
