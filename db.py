import os
import psycopg2


def _connect():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def get_games():
    conn = _connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT title, genre FROM games ORDER BY id")
            return cur.fetchall()
    finally:
        conn.close()


def add_game(title, genre=None):
    conn = _connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO games (title, genre) VALUES (%s, %s) RETURNING id",
                (title, genre),
            )
            return cur.fetchone()[0]
    finally:
        conn.close()
