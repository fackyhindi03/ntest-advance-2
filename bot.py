#!/usr/bin/env python3
# bot.py

import os
import logging
from flask import Flask, request
from telegram import (
    Bot,
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    ParseMode,
)
from telegram.ext import Dispatcher, CommandHandler, CallbackQueryHandler, CallbackContext

from hianimez_scraper import (
    search_anime,
    get_episodes_list,
    extract_episode_stream_and_subtitle,
)
from utils import download_and_rename_subtitle

# ——————————————————————————————————————————————————————————————
# 1) Load environment variables
# ——————————————————————————————————————————————————————————————
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN environment variable is not set")

KOYEB_APP_URL = os.getenv("KOYEB_APP_URL")
if not KOYEB_APP_URL:
    raise RuntimeError(
        "KOYEB_APP_URL environment variable is not set. It must be your bot’s public HTTPS URL (no trailing slash)."
    )

ANIWATCH_API_BASE = os.getenv("ANIWATCH_API_BASE")
if not ANIWATCH_API_BASE:
    raise RuntimeError(
        "ANIWATCH_API_BASE environment variable is not set. It should be your AniWatch API URL."
    )

# ——————————————————————————————————————————————————————————————
# 2) Initialize Bot + Dispatcher
# ——————————————————————————————————————————————————————————————
bot = Bot(token=TELEGRAM_TOKEN)
dispatcher = Dispatcher(bot, None, workers=4, use_context=True)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ——————————————————————————————————————————————————————————————
# 3) In-memory caches for search results & episode lists per chat
# ——————————————————————————————————————————————————————————————
search_cache = {}   # chat_id → [ (title, slug), … ]
episode_cache = {}  # chat_id → [ (ep_num, ep_slug), … ]


# ——————————————————————————————————————————————————————————————
# 4) /start handler
# ——————————————————————————————————————————————————————————————
def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "👋 Hello! I can help you search anime on hianimez.to and\n"
        " extract the SUB-HD2 (1080p) HLS link + English subtitles.\n\n"
        "Use /search <anime name> to begin."
    )


# ——————————————————————————————————————————————————————————————
# 5) /search handler
# ——————————————————————————————————————————————————————————————
def search_command(update: Update, context: CallbackContext):
    if len(context.args) == 0:
        update.message.reply_text("Please provide an anime name. Example: /search Naruto")
        return

    chat_id = update.effective_chat.id
    query = " ".join(context.args).strip()
    msg = update.message.reply_text(f"🔍 Searching for \"{query}\"…")

    try:
        results = search_anime(query)
    except Exception as e:
        logger.error(f"Search error: {e}", exc_info=True)
        msg.edit_text("❌ Search error; please try again later.")
        return

    if not results:
        msg.edit_text(f"No anime found matching \"{query}\".")
        return

    # Store (title, slug) in search_cache[chat_id]
    search_cache[chat_id] = [(title, slug) for title, anime_url, slug in results]

    buttons = []
    for idx, (title, slug) in enumerate(search_cache[chat_id]):
        # callback_data = "anime_idx:<idx>"
        buttons.append([InlineKeyboardButton(title, callback_data=f"anime_idx:{idx}")])

    reply_markup = InlineKeyboardMarkup(buttons)
    msg.edit_text("Select the anime you want:", reply_markup=reply_markup)


# ——————————————————————————————————————————————————————————————
# 6) Callback when user taps an anime (anime_idx callback)
# ——————————————————————————————————————————————————————————————
def anime_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    chat_id = query.message.chat.id
    data = query.data  # "anime_idx:<i>"
    try:
        _, idx_str = data.split(":", maxsplit=1)
        idx = int(idx_str)
    except:
        query.edit_message_text("❌ Internal error: invalid anime selection.")
        return

    anime_list = search_cache.get(chat_id, [])
    if idx < 0 or idx >= len(anime_list):
        query.edit_message_text("❌ Internal error: anime index out of range.")
        return

    title, slug = anime_list[idx]
    anime_url = f"https://hianimez.to/watch/{slug}"

    msg = query.edit_message_text(
        f"🔍 Fetching episodes for *{title}*…", parse_mode=ParseMode.MARKDOWN_V2
    )

    try:
        episodes = get_episodes_list(anime_url)
    except Exception as e:
        logger.error(f"Error fetching episodes: {e}", exc_info=True)
        query.edit_message_text("❌ Failed to retrieve episodes for that anime.")
        return

    if not episodes:
        query.edit_message_text("No episodes found for that anime.")
        return

    # Store (ep_num, ep_slug) in episode_cache[chat_id]
    episode_cache[chat_id] = []
    for ep_num, ep_url in episodes:
        ep_slug = ep_url.rstrip("/").split("/")[-1]
        episode_cache[chat_id].append((ep_num, ep_slug))

    buttons = []
    for i, (ep_num, ep_slug) in enumerate(episode_cache[chat_id]):
        buttons.append([InlineKeyboardButton(f"Episode {ep_num}", callback_data=f"episode_idx:{i}")])

    reply_markup = InlineKeyboardMarkup(buttons)
    query.edit_message_text("Select an episode:", reply_markup=reply_markup)


# ——————————————————————————————————————————————————————————————
# 7) Callback when user taps an episode (episode_idx callback)
# ——————————————————————————————————————————————————————————————
def episode_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    chat_id = query.message.chat.id
    data = query.data  # "episode_idx:<i>"
    try:
        _, idx_str = data.split(":", maxsplit=1)
        idx = int(idx_str)
    except:
        query.edit_message_text("❌ Internal error: invalid episode selection.")
        return

    ep_list = episode_cache.get(chat_id, [])
    if idx < 0 or idx >= len(ep_list):
        query.edit_message_text("❌ Internal error: episode index out of range.")
        return

    ep_num, ep_slug = ep_list[idx]
    # Now call extract with (ep_slug, ep_num), not a full URL:
    msg = query.edit_message_text(
        f"🔄 Retrieving SUB HD-2 (1080p) link and English subtitle for Episode {ep_num}…"
    )

    try:
        hls_link, subtitle_url = extract_episode_stream_and_subtitle(ep_slug, ep_num)
    except Exception as e:
        logger.error(f"Error extracting episode data: {e}", exc_info=True)
        query.edit_message_text(f"❌ Failed to extract data for Episode {ep_num}.")
        return

    if not hls_link:
        query.edit_message_text(
            f"😔 Could not find a SUB HD-2 (1080p) stream for Episode {ep_num}."
        )
        return

    text = (
        f"🎬 *Episode {ep_num}*\n\n"
        f"🔗 *1080p (SUB HD-2) HLS Link:* \n"
        f"`{hls_link}`\n\n"
    )

    if not subtitle_url:
        text += "❗ No English subtitle (.vtt) found.\n"
        query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)
        return

    try:
        local_vtt = download_and_rename_subtitle(subtitle_url, ep_num, cache_dir="subtitles_cache")
    except Exception as e:
        logger.error(f"Error downloading/renaming subtitle: {e}", exc_info=True)
        text += "⚠️ Found a subtitle URL but failed to download it.\n"
        query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)
        return

    text += f"✅ English subtitle downloaded as `Episode {ep_num}.vtt`."
    query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)

    with open(local_vtt, "rb") as f:
        query.message.reply_document(
            document=InputFile(f, filename=f"Episode {ep_num}.vtt"),
            caption=f"Here is the subtitle for Episode {ep_num}.",
        )

    try:
        os.remove(local_vtt)
    except OSError:
        pass


# ——————————————————————————————————————————————————————————————
# 8) Error handler
# ——————————————————————————————————————————————————————————————
def error_handler(update: object, context: CallbackContext):
    logger.error("Exception while handling an update:", exc_info=context.error)
    if isinstance(update, Update) and update.callback_query:
        update.callback_query.message.reply_text("⚠️ Oops, something went wrong.")


# Register all handlers
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("search", search_command))
dispatcher.add_handler(CallbackQueryHandler(anime_callback, pattern=r"^anime_idx:"))
dispatcher.add_handler(CallbackQueryHandler(episode_callback, pattern=r"^episode_idx:"))
dispatcher.add_error_handler(error_handler)


# ——————————————————————————————————————————————————————————————
# 9) Flask app for webhook + health check
# ——————————————————————————————————————————————————————————————
app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def webhook_handler():
    data = request.get_json(force=True)
    update = Update.de_json(data, bot)
    dispatcher.process_update(update)
    return "OK", 200

@app.route("/", methods=["GET"])
def health_check():
    return "OK", 200


# ——————————————————————————————————————————————————————————————
# 10) On startup, set Telegram webhook to <KOYEB_APP_URL>/webhook
# ——————————————————————————————————————————————————————————————
if __name__ == "__main__":
    webhook_url = f"{KOYEB_APP_URL}/webhook"
    try:
        bot.set_webhook(webhook_url)
        logger.info(f"Successfully set webhook to {webhook_url}")
    except Exception as ex:
        logger.error(f"Failed to set webhook: {ex}", exc_info=True)
        raise

    os.makedirs("subtitles_cache", exist_ok=True)
    logger.info("Starting Flask server on port 8080…")
    app.run(host="0.0.0.0", port=8080)
