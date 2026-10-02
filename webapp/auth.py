import os
import json
import time
import hmac
import hashlib
from urllib.parse import parse_qsl

BOT_TOKEN = os.environ["BOT_TOKEN"]


def get_user(init_data: str):
    data = dict(parse_qsl(init_data))
    received_hash = data.pop("hash", None)
    if not received_hash:
        return None

    check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calc_hash, received_hash):
        return None
    if time.time() - int(data.get("auth_date", 0)) > 3600:
        return None
    return json.loads(data["user"])