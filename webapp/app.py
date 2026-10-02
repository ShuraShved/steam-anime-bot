import os

import psycopg2
from flask import Flask, request, jsonify

from auth import get_user

app = Flask(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]


@app.get("/api/hello")
def hello():
    user = get_user(request.headers.get("X-Init-Data", ""))
    if not user:
        return jsonify(error="Open Mini App from Telegram."), 401

    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT id, title, genre FROM games ORDER BY id")
            games = [{"id": r[0], "title": r[1], "genre": r[2]} for r in cur.fetchall()]
    finally:
        conn.close()

    return jsonify(greeting=f"Hello, {user['first_name']}!", games=games)