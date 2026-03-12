import hashlib
from datetime import datetime, timezone

from database.db import get_db


async def ensure_user(user_id: int, username: str | None, first_name: str | None):
    db = await get_db()
    await db.execute(
        """INSERT INTO users (user_id, username, first_name)
           VALUES (?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name""",
        (user_id, username, first_name),
    )
    await db.commit()


async def create_order(user_id: int, text: str, word_count: int, price: float) -> int:
    db = await get_db()
    text_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
    cursor = await db.execute(
        "INSERT INTO orders (user_id, text_hash, word_count, price) VALUES (?, ?, ?, ?)",
        (user_id, text_hash, word_count, price),
    )
    await db.commit()
    return cursor.lastrowid


async def get_order(order_id: int) -> dict | None:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
    row = await cursor.fetchone()
    if row is None:
        return None
    return dict(row)


async def update_order_status(order_id: int, status: str):
    db = await get_db()
    extra = ""
    params: list = [status, order_id]
    if status == "completed":
        extra = ", completed_at = ?"
        params = [status, datetime.now(timezone.utc).isoformat(), order_id]
    await db.execute(
        f"UPDATE orders SET status = ?{extra} WHERE id = ?",
        params,
    )
    await db.commit()


async def update_user_stats(user_id: int, word_count: int, price: float):
    db = await get_db()
    await db.execute(
        "UPDATE users SET total_words_used = total_words_used + ?, total_paid = total_paid + ? WHERE user_id = ?",
        (word_count, price, user_id),
    )
    await db.commit()


async def get_monthly_stats() -> dict:
    db = await get_db()
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    cursor = await db.execute(
        "SELECT COUNT(*) as cnt, COALESCE(SUM(price), 0) as revenue, COALESCE(SUM(word_count), 0) as words "
        "FROM orders WHERE status = 'completed' AND strftime('%Y-%m', completed_at) = ?",
        (month,),
    )
    row = await cursor.fetchone()
    return dict(row)


async def get_pending_orders_by_user(user_id: int) -> list[dict]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM orders WHERE user_id = ? AND status IN ('pending', 'paid') ORDER BY created_at DESC",
        (user_id,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_user_orders(user_id: int, limit: int = 10) -> list[dict]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT id, word_count, price, status, created_at FROM orders "
        "WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_user_summary(user_id: int) -> dict:
    db = await get_db()
    cursor = await db.execute(
        "SELECT total_words_used, total_paid FROM users WHERE user_id = ?",
        (user_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return {"total_words_used": 0, "total_paid": 0.0}
    return dict(row)


async def get_all_user_ids() -> list[int]:
    db = await get_db()
    cursor = await db.execute("SELECT user_id FROM users")
    rows = await cursor.fetchall()
    return [row["user_id"] for row in rows]
