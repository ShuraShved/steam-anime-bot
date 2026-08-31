import asyncio
import re
from pathlib import Path
import json
import html
from datetime import datetime, date, time, timedelta
import os

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, InputMediaPhoto
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler
from telegram.constants import ParseMode
import requests
from mistralai.client import Mistral
from dotenv import load_dotenv
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("steam_anime_bot")

BASE_DIR = Path(__file__).resolve().parent
STORAGE_PATH = BASE_DIR / "storage.json"

ANIME_TAG_ID = 4085
GAMES_CATEGORY = 998
DEMOS_CATEGORY = 10
SEARCH_URL = "https://store.steampowered.com/search/results/"

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SMTP_HOST = os.environ["SMTP_HOST"]
SMTP_PORT = int(os.environ.get("SMTP_PORT", 465))
SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASSWORD = os.environ["SMTP_PASSWORD"]
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER)


def load_storage() -> dict:
    if STORAGE_PATH.exists():
        data = json.loads(STORAGE_PATH.read_text(encoding="utf-8"))
    else:
        data = {}
    data.setdefault("followers", {})
    data.setdefault("pending_appids", [])
    data.setdefault("released_appids", [])
    data.setdefault("next_seq", 1)
    data.setdefault("last_summary_date", date.today().isoformat())
    return data


def save_storage(data: dict) -> None:
    STORAGE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_released_anime_games(category: int = GAMES_CATEGORY) -> list[int]:
    appids: list[int] = []
    start = 0
    count = 25

    while True:
        params = {
            "query": "",
            "start": start,
            "count": count,
            "tags": ANIME_TAG_ID,
            "category1": category,
            "sort_by": "Released_DESC",
            "json": 1,
            "l": "english"
        }

        try:
            resp = requests.get(
                SEARCH_URL,
                params=params,
                timeout=15,
            )
            data = resp.json()
            items = data.get("items", [])

            for item in items:
                logo = item.get("logo", "")
                appid_match = re.compile(r"/apps/(\d+)/").search(logo)
                if appid_match:
                    appids.append(int(appid_match.group(1)))

        except Exception as e:
            log.warning("Error while looking for games: %s", e)

        res = list(dict.fromkeys(appids))
        res.reverse()
        return res


# Steam treats demos (category=10) as standalone apps, so their API
# responses do not include the full game's actual release date.
# This function uses the demo's "fullgame" JSON parameter to fetch
# the parent appid and retrieve its true "coming_soon" status and release date.
def fetch_full_game(appid: int) -> tuple | None:
    try:
        resp = requests.get(
            "https://store.steampowered.com/api/appdetails",
            params={"appids": appid, "l": "english", "cc":"us"},
            timeout=15,
        )
        payload = resp.json().get(str(appid))

    except Exception as e:
        log.warning("Request error game details for %s: %s", appid, e)
        return None

    if not payload or not payload.get("success"):
        return None

    data = payload["data"]
    release = data.get("release_date", {}) # {'coming_soon': ?, 'date': ?}
    release_date_str = release.get("date", "coming soon") # "Aug 20, 2026" or "Q4 2026"
    desc = data.get("short_description", "")

    return desc, release_date_str


def fetch_game_details(appid: int) -> dict | None:
    try:
        resp = requests.get(
            "https://store.steampowered.com/api/appdetails",
            params={"appids": appid, "l": "english", "cc":"us"},
            timeout=15,
        )
        payload = resp.json().get(str(appid))

    except Exception as e:
        log.warning("Request error game details for %s: %s", appid, e)
        return None

    if not payload or not payload.get("success"):
        return None

    data = payload["data"]
    description = data.get("short_description", "")
    release = data.get("release_date", {}) # {'coming_soon': ?, 'date': ?}
    release_date_str = release.get("date", "coming soon") # "Aug 20, 2026" or "Q4 2026"
    parsed_date = datetime.strptime(release_date_str.strip(), "%b %d, %Y").date()

    if data.get("fullgame"):
        desc, eta = fetch_full_game(data.get("fullgame").get("appid"))
        description = desc
        release_date_str = "ETA: " + eta

    if data["is_free"] == "true":
        price_formatted = "Free"
    else:
        price = data.get("price_overview", {})
        price_formatted = price.get("final_formatted", "Free")

    return {
        "type": data.get("type"),
        "name": data.get("name", "Couldn't find name"),
        "description": description,
        "image": data.get("header_image"),
        "release_date_str": release_date_str, # full game release date or scheduled release if demo
        "parsed_date": parsed_date, # actual item release date
        "coming_soon": bool(release.get("coming_soon", False)),
        "price": price_formatted
    }


def build_caption(appid: int, info: dict) -> str:
    name = html.escape(info["name"])
    desc = html.escape(info["description"])
    price = info["price"]
    if len(desc) > 500:
        desc = desc[:500].rsplit(" ", 1)[0] + "…"
    return (
        f"🎉 <b>{name}</b> — released!\n"
        f"Release date: {html.escape(str(info['release_date']))}\n\n"
        f"{desc}\n\n"
        f"{price}\n\n"
        f"https://store.steampowered.com/app/{appid}"
    )


async def run_check_releases(context: ContextTypes.DEFAULT_TYPE) -> None:
    storage = load_storage()
    released = storage["released_appids"]
    known_appids = {entry["appid"] for entry in released}

    game_appids = await asyncio.to_thread(fetch_released_anime_games, category=GAMES_CATEGORY)
    demo_appids = await asyncio.to_thread(fetch_released_anime_games, category=DEMOS_CATEGORY)

    new_game_appids = [appid for appid in game_appids if appid not in known_appids]
    new_demo_appids = [appid for appid in demo_appids if appid not in known_appids]

    log.info("Found %d new released games.", len(new_game_appids))
    log.info("Found %d new released demos.", len(new_demo_appids))

    for appid in new_game_appids + new_demo_appids:
        info = await asyncio.to_thread(fetch_game_details, appid)
        await asyncio.sleep(1.5)

        if info is None or info["coming_soon"]:
            continue

        game_date = info["parsed_date"]
        if game_date.isoformat() != date.today():
            continue

        seq = storage["next_seq"]
        storage["next_seq"] += 1
        released.append({
            "seq": seq,
            "appid": appid,
            "type": info["type"],
            "name": info["name"],
            "description": info["description"],
            "image": info["image"],
            "price": info["price"],
            "release_date": info["release_date_str"],
            "release_iso": game_date.isoformat(),
        })

    storage["released_appids"] = released
    save_storage(storage)
    await deliver_pending(context)


async def deliver_pending(context: ContextTypes.DEFAULT_TYPE, chat_id: str | None = None) -> None:
    storage = load_storage()
    followers = storage.get("followers", {})
    released = storage["released_appids"]

    targets = {chat_id: followers[chat_id]} if chat_id is not None else followers

    for chat_id, info in targets.items():
        pref_games = info.get("want_games", True)
        pref_demos = info.get("want_demos", True)
        games_cursor = info.get("games_cursor", 0)
        demos_cursor = info.get("demos_cursor", 0)

        pending_games = [e for e in released if e["type"] == "game"
                         and e["seq"] > games_cursor]
        pending_demos = [e for e in released if e["type"] == "demo"
                         and e["seq"] > demos_cursor]
        pending = pending_games + pending_demos

        if not pending:
            continue

        max_game_seq_sent = games_cursor
        max_demo_seq_sent = demos_cursor
        for app in pending:
            caption = build_caption(app["appid"], app)
            try:
                if pref_games and app["type"] == "game":
                    if app["image"]:
                        await context.bot.send_photo(chat_id, photo=app["image"], caption=caption,
                                                     parse_mode=ParseMode.HTML)
                    else:
                        await context.bot.send_message(chat_id, caption, parse_mode=ParseMode.HTML)
                    max_game_seq_sent = app["seq"]

                elif pref_demos and app["type"] == "demo":
                    if app["image"]:
                        await context.bot.send_photo(chat_id, photo=app["image"], caption=caption,
                                                     parse_mode=ParseMode.HTML)
                    else:
                        await context.bot.send_message(chat_id, caption, parse_mode=ParseMode.HTML)
                    max_demo_seq_sent = app["seq"]
            except Exception as e:
                log.warning("Couldn't send message in chat %s: %s", chat_id, e)
                break

        followers[chat_id]["games_cursor"] = max_game_seq_sent
        followers[chat_id]["demos_cursor"] = max_demo_seq_sent

    storage["followers"] = followers
    save_storage(storage)


async def generate_and_send_summary(context: ContextTypes.DEFAULT_TYPE, day: date) -> None:
    storage = load_storage()
    client = Mistral(api_key=os.getenv("AI_KEY"))
    released = storage.get("released_appids", [])

    day_iso = day.isoformat()
    game_list = [appid for appid in released if appid["type"] == "game" and appid["release_iso"] == day_iso]
    demo_list = [appid for appid in released if appid["type"] == "demo" and appid["release_iso"] == day_iso]

    if not game_list and not demo_list:
        return

    followers = storage["followers"]
    need_games = any(pref["want_games"] and not pref["want_demos"] for pref in followers.values())
    need_demos = any(pref["want_demos"] and not pref["want_games"] for pref in followers.values())
    need_combo = any(pref["want_games"] and pref["want_demos"] for pref in followers.values())

    today = "today" if date.today().isoformat() == day_iso else day_iso

    def build_prompt(appids):
        return (
            "You have a list of games released today, each in the form 'name: description', one per line. "
            "Summarize the games and genres based on their descriptions, and pick up to 3 of the most exciting "
            "ones to recommend. First line: write the number of games and date. Like: "
            f"'5 new games dropped {today}! 🕹️🎉' or think of something alike yourself. "
            "Second line: write the genres. "
            "Third line: write a summary and chosen ones to recommend. Add emojis and write in a friendly tone. "
            "The output will be sent using Telegram HTML parse mode. "
            "Use only these Telegram HTML tags: "
            "<b>, <strong>, <i>, <em>, <u>, <ins>, <s>, <strike>, <del>,"
            "<code>, <pre>, <a href='URL'>, and <blockquote>. "
            "Never use: "
            "<span>, <div>, <p>, <br>, <font>, <style>, <section>, "
            "Markdown syntax, CSS, or arbitrary HTML attributes. "
            "Output only the final message. Do not output explanations, "
            "HTML code fences, or any tag not listed above. "
            "Don't forget to link games you'll reference like <a href='https://example.com'>Link</a>.\n"
            "The ones you chose to recommend, at the very end of your response, strictly list "
            "their 'appid's inside the tag <recommendations>, separated by commas. "
            "Don't write anything else inside this tag. "
            "Example: <recommendations>123456, 789012</recommendations>.\n"
            f"Here is the list:\n{appids}"
        )

    interaction_game = interaction_demo = interaction_combo = None
    if need_games and game_list:
        try:
            interaction_game = client.chat.complete(
                model="mistral-medium-latest",
                messages=[
                    {"role": "user", "content": build_prompt(game_list)}
                ],
            )
        except Exception as e:
            log.warning("AI API is down or unreachable: %s", e)
    if need_demos and demo_list:
        try:
            interaction_demo = client.chat.complete(
                model="mistral-medium-latest",
                messages=[
                    {"role": "user", "content": build_prompt(demo_list)}
                ],
            )
        except Exception as e:
            log.warning("AI API is down or unreachable: %s", e)
    if need_combo and (game_list or demo_list):
        try:
            interaction_combo = client.chat.complete(
                model="mistral-medium-latest",
                messages=[
                    {"role": "user", "content": build_prompt(game_list + demo_list)}
                ],
            )
        except Exception as e:
            log.warning("AI API is down or unreachable: %s", e)

    def parse_response(response: str, game_list: list, demo_list: list) -> tuple:
        match = re.search(r'<recommendations>(.*?)</recommendations>', response, re.IGNORECASE | re.DOTALL)
        recommended_images = []
        recommended_games = []
        clean_text = response

        if match:
            all_games = game_list + demo_list
            raw_ids = match.group(1)
            recommended_appids = [appid.strip() for appid in raw_ids.split(',') if appid.strip().isdigit()]

            for appid_str in recommended_appids:
                found_game = next((g for g in all_games if str(g.get("appid")) == appid_str), None)
                if found_game:
                    recommended_games.append(found_game)
                    if found_game.get("image"):
                        recommended_images.append(found_game["image"])

            clean_text = re.sub(r'<recommendations>.*?</recommendations>', '', response,
                                flags=re.IGNORECASE | re.DOTALL).strip()

        return clean_text, recommended_images, recommended_games

    for chat_id, prefs in followers.items():
        if prefs["want_games"] and prefs["want_demos"] and interaction_combo:
            text, images, games = parse_response(interaction_combo.choices[0].message.content, game_list, demo_list)
        elif prefs["want_games"] and not prefs["want_demos"] and interaction_game:
            text, images, games = parse_response(interaction_game.choices[0].message.content, game_list, [])
        elif prefs["want_demos"] and not prefs["want_games"] and interaction_demo:
            text, images, games = parse_response(interaction_demo.choices[0].message.content, [], demo_list)
        else:
            continue

        if not images:
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                link_preview_options=LinkPreviewOptions(
                    is_disabled=True
                ),
            )
            continue

        media_group = []
        for i, img_url in enumerate(images):
            if i == 0:
                media_group.append(
                    InputMediaPhoto(media=img_url, caption=text, parse_mode="HTML")
                )
            else:
                media_group.append(
                    InputMediaPhoto(media=img_url)
                )

        try:
            await context.bot.send_media_group(
                chat_id=chat_id,
                media=media_group,
            )
        except Exception as e:
            log.warning("Couldn't send summarize message in chat %s: %s", chat_id, e)

        if prefs["email"]:
            try:
                await asyncio.to_thread(send_summary_email,
                                            prefs["email"],
                                            f"Steam anime releases {day}",
                                            text,
                                            games
                                        )
            except Exception as e:
                log.warning("Couldn't send mail to %s: %s", prefs["email"], e)


async def daily_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    storage = load_storage()
    last_date = date.fromisoformat(storage.get("last_summary_date", date.today().isoformat()))

    d = last_date + timedelta(days=1)
    while d <= date.today():
        await generate_and_send_summary(context, d)
        d += timedelta(days=1)

    storage["last_summary_date"] = date.today().isoformat()
    save_storage(storage)


def send_summary_email(to_email: str, subject: str, text: str, games: list[dict]) -> None:
    if not games:
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = to_email

    def esc(s: str) -> str:
        return html.escape(s or "")

    def card(game: dict) -> str:
        return f'''
            <h2 style="color: white; margin-bottom: 10px;">{esc(game['name'])}</h2>
            <img src="{game["image"]}" style="max-width: 100%; height: auto; display: block; border-radius: 4px;">
            <p style='color: grey; line-height: 1.5;'>{esc(game.get('description', ''))}</p>
            <a href='https://store.steampowered.com/app/{game['appid']}' 
            style='display: inline-block; padding: 10px 20px; 
            background-color: #001154; color: white; text-decoration: none; 
            border-radius: 4px; font-weight: bold;'>Open in Steam</a>
        '''

    html_parts = ["<html><body style='font-family: Arial, sans-serif; background-color: black; padding: 20px 0;'>",
                  "<table width='100%' max-width='600' align='center' style='max-width: 600px; margin: 0 auto; "
                  "background-color: #1a1a1a; padding: 20px; border-radius: 8px;'>",
                  "<tr><td>",
                  '<table width="100%" border="0" cellspacing="0" cellpadding="0" style="margin-bottom: 15px;">']

    html_parts.append(f'''
        <tr>
            <td colspan="2" align="center" style="padding-bottom: 10px;">{card(games[0])}
                <hr style="border: none; border-top: 1px solid grey; margin: 25px 0;">
            </td>
        </tr>
    ''')

    html_parts.append('<tr>')
    html_parts.append('<td align="center" width="50%" valign="top" style="padding-right: 5px;">')

    html_parts.append(card(games[1]) if len(games) >= 2
                      else '''
                        <div style="background-color: #2b2b2b; 
                        border-radius: 4px; width: 100%; height: 140px;">&nbsp;</div>
                      ''')
    html_parts.append('</td>')

    html_parts.append('<td align="center" width="50%" valign="top" style="padding-left: 5px;">')
    html_parts.append(card(games[2]) if len(games) == 3
                      else '''
                        <div style="background-color: #2b2b2b; 
                        border-radius: 4px; width: 100%; height: 140px;">&nbsp;</div>
                      ''')

    html_parts.append("</td></tr></table>")

    if text:
        html_parts.append("<h3 style='color: white;'>Summary:</h3>")
        html_parts.append(f'''
            <div style='background-color: #2b2b2b; 
            padding: 15px; border-left: 4px solid #001154; color: white; line-height: 1.6;'>{text}</div>
        ''')

    # Footer
    html_parts.append('''
        <table width="100%" align="center" style="max-width: 600px; margin: 20px auto 0; 
        padding: 20px; background-color: #1f354d; color: grey;
        font-size: 12px; text-align: center; border-radius: 8px;">
            <tr><td>
                <p style="margin: 0 0 10px 0; 
                color: grey;">You received this mail because you follow @SteamAnimeBot.</p>
                <p style="margin: 0 0 10px 0;">
                    <a href="https://t.me/SteamAnimeBot?start=unsetemail" style="color: #73bdff; 
                    text-decoration: none;">Unfollow mail summaries</a>
                    &nbsp;|&nbsp;
                    <a href="https://github.com/ShuraShved/steam-anime-bot" style="color: #73bdff; 
                    text-decoration: none;">GitHub source code</a>
                </p>
                <p style="margin: 15px 0 0 0; text-align: right; color: grey;">made with 
                <span style="color: #730000;">♥</span> by ShuraShved.</p>
            </td></tr>
        </table>
    ''')
    html_parts.append("</body></html>")
    msg.attach(MIMEText("".join(html_parts), "html", "utf-8"))

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as server:
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_FROM, [to_email], msg.as_string())


def build_settings_keyboard(prefs: dict) -> InlineKeyboardMarkup:
    games_label = "✅ Games" if prefs.get("want_games", True) else "❌ Games"
    demos_label = "✅ Demos" if prefs.get("want_demos", True) else "❌ Demos"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(games_label, callback_data="toggle:games"),
            InlineKeyboardButton(demos_label, callback_data="toggle:demos")
        ]
    ])


async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    storage = load_storage()
    chat_id = str(update.effective_chat.id)
    prefs = storage["followers"].get(chat_id, {})
    await update.message.reply_text("Manage your follows:", reply_markup=build_settings_keyboard(prefs))


async def on_toggle_pressed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    storage = load_storage()
    chat_id = str(update.effective_chat.id)
    if chat_id not in storage["followers"]:
        return

    _, key = query.data.split(":")
    pref_key = f"want_{key}"

    # move the cursor so user doesn't get flooded with a month's worth of games/demos while unfollowed from one
    if not storage["followers"][chat_id][pref_key]:
        today = date.today().isoformat()
        older_seqs = [e["seq"] for e in storage["released_appids"] if e["type"] == f"{key[:-1]}"
                      and e["release_iso"] < today]
        storage["followers"][chat_id][f"{key}_cursor"] = max(older_seqs, default=0)

    storage["followers"][chat_id][pref_key] = not storage["followers"][chat_id].get(pref_key, True)
    save_storage(storage)

    await query.edit_message_reply_markup(
        reply_markup=build_settings_keyboard(storage["followers"][chat_id])
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.args:
        payload = context.args[0]

        if payload == "unsetemail":
            await unset_email(update, context)
            return

    await update.message.reply_text("Hello! This is a bot that will send you new released anime games.\n\n"
                                    "Here is the list of all available commands:\n"
                                    "/start – 👋 Greeting message\n"
                                    "/follow – 🔒 Follow new anime game releases\n"
                                    "/unfollow – 🔓 Unfollow new anime game releases\n"
                                    "/settings – 📑 Manage your follow preferences\n"
                                    "/setemail your@email.com – ✉️ Set email for daily summaries\n"
                                    "/unsetemail – 🔕 Remove email for daily summaries\n"
                                    "/kawaii – 🥚")


async def follow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    storage = load_storage()
    chat_id = str(update.effective_chat.id)

    if chat_id not in storage["followers"]:
        today = date.today().isoformat()
        older_games_seqs = [e["seq"] for e in storage["released_appids"] if e["type"] == "game"
                            and e["release_iso"] < today]
        older_demos_seqs = [e["seq"] for e in storage["released_appids"] if e["type"] == "demo"
                            and e["release_iso"] < today]

        storage["followers"][chat_id] = {
            "games_cursor": max(older_games_seqs, default=0),
            "demos_cursor": max(older_demos_seqs, default=0),
            "want_games": True,
            "want_demos": True,
            "email": ""
        }

        save_storage(storage)
        await update.message.reply_text("Following.")
        await deliver_pending(context)
    else:
        await update.message.reply_text("This user is already following.")


async def unfollow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    storage = load_storage()
    chat_id = str(update.effective_chat.id)
    if chat_id in storage["followers"]:
        storage["followers"].pop(chat_id)
        save_storage(storage)
        await update.message.reply_text("Unfollowed.")
    else:
        await update.message.reply_text("This user is not following.")


async def set_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    storage = load_storage()
    if chat_id not in storage["followers"]:
        await update.message.reply_text("You need to follow to do that /follow.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /setemail your@email.com")
        return

    email = context.args[0]
    if not EMAIL_RE.match(email):
        await update.message.reply_text("That doesn't look like a valid email. Please check the spelling.")
        return

    storage["followers"][chat_id]["email"] = email
    save_storage(storage)
    await update.message.reply_text(f"All set, daily summaries will be sent to {email}.")


async def unset_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    storage = load_storage()

    if chat_id not in storage["followers"]:
        await update.message.reply_text("You need to follow to do that /follow.")
        return
    if not storage["followers"][chat_id].get("email"):
        await update.message.reply_text("You need to set an email first. Use /setemail your@email.com.")
        return

    email = storage["followers"][chat_id]["email"]
    storage["followers"][chat_id]["email"] = ""
    save_storage(storage)
    await update.message.reply_text(f"Will no longer send daily summaries to {email}.")


async def kawaii(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"O /// O"
    )


if __name__ == '__main__':
    token = os.getenv("BOT_TOKEN")
    interval_minutes = int(os.getenv("CHECK_INTERVAL_MINUTES"))

    application = ApplicationBuilder().token(token).build()

    start_handler = CommandHandler('start', start)
    follow_handler = CommandHandler('follow', follow)
    unfollow_handler = CommandHandler('unfollow', unfollow)
    kawaii_handler = CommandHandler('kawaii', kawaii)
    settings_handler = CommandHandler("settings", settings)
    set_email_handler = CommandHandler("setemail", set_email)
    unset_email_handler = CommandHandler("unsetemail", unset_email)
    toggle_button_handler = CallbackQueryHandler(on_toggle_pressed, pattern=r"^toggle:")
    application.add_handler(start_handler)
    application.add_handler(follow_handler)
    application.add_handler(unfollow_handler)
    application.add_handler(unfollow_handler)
    application.add_handler(kawaii_handler)
    application.add_handler(settings_handler)
    application.add_handler(set_email_handler)
    application.add_handler(unset_email_handler)
    application.add_handler(toggle_button_handler)

    application.job_queue.run_repeating(
        run_check_releases,
        interval=interval_minutes * 60,
        first=10,
        name="run_check",
    )

    application.job_queue.run_daily(
        daily_summary,
        time=time(hour=17, minute=0),
        name="daily_summary",
    )

    log.info("Bot started, check interval: %s min.", interval_minutes)
    application.run_polling()
