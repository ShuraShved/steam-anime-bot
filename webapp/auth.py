import os
import json
import time
import hmac
import hashlib
from functools import wraps
from urllib.parse import parse_qsl

from flask import g, jsonify, request

BOT_TOKEN = os.environ["BOT_TOKEN"]

MAX_AGE_SECONDS = 24 * 60 * 60


def get_user(init_data: str):
    """Verify Telegram's signature. Returns the user dict or None."""
    data = dict(parse_qsl(init_data))
    received_hash = data.pop("hash", None)
    if not received_hash or "user" not in data:
        return None

    check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc_hash, received_hash):
        return None

    try:
        age = time.time() - int(data["auth_date"])
    except (KeyError, ValueError):
        return None
    if age > MAX_AGE_SECONDS:
        return None
    return json.loads(data["user"])


def require_user(view):
    """Decorator: 401 unless the request carries valid initData. User -> g.user."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        user = get_user(request.headers.get("X-Init-Data", ""))
        if not user:
            return jsonify(error="Open the Mini App from Telegram."), 401
        g.user = user
        return view(*args, **kwargs)
    return wrapper