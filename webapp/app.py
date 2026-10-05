from datetime import date

from flask import Flask, g, jsonify, request

import db
from auth import require_user

app = Flask(__name__)


@app.get("/api/hello")
@require_user
def hello():
    following = db.get_db_user_id(g.user["id"]) is not None
    return jsonify(greeting=f"Hello, {g.user.get('first_name', 'friend')}!", following=following)


@app.get("/api/apps")
@require_user
def apps_by_date():
    try:
        release_date = date.fromisoformat(request.args.get("date", ""))
    except ValueError:
        return jsonify(error="Invalid or missing date, expected YYYY-MM-DD."), 400

    # None if the user never followed in the bot: the list still works, just without stars.
    db_user_id = db.get_db_user_id(g.user["id"])
    return jsonify(apps=db.get_apps_by_date(release_date, db_user_id))


@app.get("/api/summary")
@require_user
def summary():
    try:
        summary_date = date.fromisoformat(request.args.get("date", ""))
    except ValueError:
        return jsonify(error="Invalid or missing date, expected YYYY-MM-DD."), 400
    return jsonify(summary=db.get_summary(summary_date))


@app.post("/api/favorite")
@require_user
def favorite():
    body = request.get_json(silent=True) or {}
    app_id, is_fav = body.get("id"), body.get("favorite")
    if not isinstance(app_id, int) or isinstance(app_id, bool) or not isinstance(is_fav, bool):
        return jsonify(error="Expected JSON: {id: int, favorite: bool}."), 400

    # The user comes from the signed initData, never from the request body.
    db_user_id = db.get_db_user_id(g.user["id"])
    if db_user_id is None:
        return jsonify(error="You need to /follow in the bot to do that."), 403
    if not db.set_favorite(db_user_id, app_id, is_fav):
        return jsonify(error="Game not found."), 404
    return jsonify(id=app_id, favorite=is_fav)


@app.get("/api/favorite")
@require_user
def list_favorites():
    db_user_id = db.get_db_user_id(g.user["id"])
    if db_user_id is None:
        return jsonify(error="You need to /follow in the bot to do that."), 403
    return jsonify(favorites=db.get_favorites(db_user_id))


@app.errorhandler(500)
def server_error(_):
    return jsonify(error="Server error."), 500