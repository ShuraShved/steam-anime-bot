from datetime import date

from flask import Flask, g, jsonify, request

import db
from auth import require_user

app = Flask(__name__)


@app.get("/api/hello")
@require_user
def hello():
    return jsonify(greeting=f"Hello, {g.user.get('first_name', '')}!")


@app.get("/api/apps")
@require_user
def apps_by_date():
    try:
        release_date = date.fromisoformat(request.args.get("date", ""))
    except ValueError:
        return jsonify(error="Invalid or missing date, expected YYYY-MM-DD."), 400

    # None if the user has no row yet: the list still works, just without stars.
    db_user_id = db.get_db_user_id(g.user["id"])
    return jsonify(apps=db.get_apps_by_date(release_date, db_user_id))


@app.post("/api/favorite")
@require_user
def favorite():
    body = request.get_json(silent=True) or {}
    app_id, is_fav = body.get("id"), body.get("favorite")
    if not isinstance(app_id, int) or isinstance(app_id, bool) or not isinstance(is_fav, bool):
        return jsonify(error="Expected JSON: {id: int, favorite: bool}."), 400

    # The user comes from the signed initData, never from the request body.
    db_user_id = db.get_or_create_db_user_id(g.user["id"])
    if not db.set_favorite(db_user_id, app_id, is_fav):
        return jsonify(error="Game not found."), 404
    return jsonify(id=app_id, favorite=is_fav)


@app.get("/api/favorite")
@require_user
def show_favorites():
    db_user_id = db.get_db_user_id(g.user["id"])
    if not db_user_id:
        return jsonify(favorites=[])
    return jsonify(favorites=db.get_favorites(db_user_id))


@app.errorhandler(500)
def server_error(_):
    return jsonify(error="Server error."), 500