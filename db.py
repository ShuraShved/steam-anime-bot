import os
from contextlib import contextmanager

import psycopg2


@contextmanager
def _cursor():
    """One short-lived connection per call; commits on success, rolls back on error.
    DATABASE_URL is read here, not at import: bot.py imports db before load_dotenv()."""
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        with conn, conn.cursor() as cur:
            yield cur
    finally:
        conn.close()


def add_app(app_id, seq, app_type, title, genres, description, image, link, price, release_date):
    """Insert a game/demo, or refresh its data if app_id already exists.
    seq is not touched on conflict, so existing cursors stay valid."""
    with _cursor() as cur:
        cur.execute(
            """
            INSERT INTO appids (app_id, seq, type, title, genres,
                                description, image, link, price, release_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (app_id) DO UPDATE SET
                type = EXCLUDED.type, title = EXCLUDED.title,
                genres = EXCLUDED.genres, description = EXCLUDED.description,
                image = EXCLUDED.image, link = EXCLUDED.link,
                price = EXCLUDED.price, release_date = EXCLUDED.release_date
            """,
            (app_id, seq, app_type, title, genres, description, image, link, price, release_date),
        )


def add_user(chat_id, games_cursor=0, demos_cursor=0):
    """Create the user row if missing; safe to call repeatedly. Needs UNIQUE(chat_id)."""
    with _cursor() as cur:
        cur.execute(
            """
            INSERT INTO users (chat_id, games_cursor, demos_cursor)
            VALUES (%s, %s, %s)
            ON CONFLICT (chat_id) DO NOTHING
            """,
            (chat_id, games_cursor, demos_cursor),
        )


def remove_user(chat_id):
    """Delete the user row; ON DELETE CASCADE also deletes their favorites.
    Safe to call when the row doesn't exist."""
    with _cursor() as cur:
        cur.execute("DELETE FROM users WHERE chat_id = %s", (chat_id,))


def add_summary(summary_date, text, app_ids):
    """One summary per day: running it again for the same day replaces it.
    app_ids are Steam appids (appids.app_id), stored as '123,456'."""
    with _cursor() as cur:
        cur.execute(
            """
            INSERT INTO summaries (summary_date, text, app_ids)
            VALUES (%s, %s, %s)
            ON CONFLICT (summary_date) DO UPDATE
                SET text = EXCLUDED.text, app_ids = EXCLUDED.app_ids
            """,
            (summary_date, text, ",".join(map(str, app_ids))),
        )