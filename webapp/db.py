import os
from contextlib import contextmanager

import psycopg2
import psycopg2.errors
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ["DATABASE_URL"]  # on Vercel: the pooled Neon string


@contextmanager
def cursor():
    """One short-lived connection per call (serverless-friendly).
    Commits on success, rolls back on error, always closes."""
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
    finally:
        conn.close()


def get_db_user_id(chat_id: int):
    """Telegram user id -> users.id (None if the user never started the bot)."""
    with cursor() as cur:
        cur.execute("SELECT id FROM users WHERE chat_id = %s LIMIT 1", (chat_id,))
        row = cur.fetchone()
        return row["id"] if row else None


def get_or_create_db_user_id(chat_id: int) -> int:
    """Telegram user id -> users.id, creating the row on first use. Needs UNIQUE(chat_id)."""
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO users (chat_id) VALUES (%s)
            ON CONFLICT (chat_id) DO UPDATE SET chat_id = EXCLUDED.chat_id
            RETURNING id
            """,
            (chat_id,),
        )
        return cur.fetchone()["id"]


def get_apps_by_date(release_date, db_user_id):
    with cursor() as cur:
        cur.execute(
            """
            SELECT a.id, a.app_id, a.title, a.type, a.genres, a.price, a.image, a.link,
                   (f.user_id IS NOT NULL) AS is_favorite
            FROM appids a
            LEFT JOIN favorites f ON f.app_id = a.id AND f.user_id = %s
            WHERE a.release_date = %s
            ORDER BY a.id
            """,
            (db_user_id, release_date),
        )
        return cur.fetchall()


def set_favorite(db_user_id: int, app_id: int, favorite: bool) -> bool:
    """Add/remove a favorite. False if app_id does not exist."""
    try:
        with cursor() as cur:
            if favorite:
                cur.execute(
                    "INSERT INTO favorites (user_id, app_id) VALUES (%s, %s) "
                    "ON CONFLICT DO NOTHING",
                    (db_user_id, app_id),
                )
            else:
                cur.execute(
                    "DELETE FROM favorites WHERE user_id = %s AND app_id = %s",
                    (db_user_id, app_id),
                )
    except psycopg2.errors.ForeignKeyViolation:
        return False
    return True