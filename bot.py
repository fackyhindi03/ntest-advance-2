#!/usr/bin/env python3
# bot.py

import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    ParseMode,
)
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackQueryHandler,
    CallbackContext,
)

from hianimez_scraper import (
    search_anime,
    get_episodes_list,
    extract_episode_stream_and_subtitle,
)
from utils import download_and_rename_subtitle

# 1) Read the token from the environment
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", None)
if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN environment variable is not set")


# 2) Tiny HTTP health server (for “Web Service” in Koyeb)
def run_health_server():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")

    server = HTTPServer(("", 8080), Handler)
    server.serve_forever()


def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "👋 Hello! I can help you search for anime on hianimez.to "
        "and extract the SUB-HD2 (1080p) HLS link + English subtitles.\n\n"
        "Use /search <anime name> to begin."
    )


def search_command(update: Update, context: CallbackContext):
    if len(context.args) == 0:
        update.message.reply_text("Please provide an anime name. Example: /search Naruto")
        return

    query = " ".join(context.args).strip()
    msg = update.message.reply_text(f"🔍 Searching for \"{query}\" ...")

    try:
        results = search_anime(query)
    except Exception as e:
        logging.error(f"Error during search: {e}", exc_info=True)
        msg.edit_text("❌ Sorry, something went wrong while searching.")
        return

    if not results:
        msg.edit_text(f"No anime found matching \"{query}\".")
        return

    buttons = []
    for title, anime_url, _ in results:
        buttons.append([InlineKeyboardButton(title, callback_data=f"anime:{anime_url}")])

    reply_markup = InlineKeyboardMarkup(buttons)
    msg.edit_text("Select the anime you want:", reply_markup=reply_markup)


def anime_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    _, anime_url = query.data.split(":", maxsplit=1)
    try:
        episodes = get_episodes_list(anime_url)
    except Exception as e:
        logging.error(f"Error fetching episodes: {e}", exc_info=True)
        query.edit_message_text("❌ Failed to retrieve episodes for that anime.")
        return

    if not episodes:
        query.edit_message_text("No episodes found for that anime.")
        return

    buttons = []
    for ep_num, ep_url in episodes:
        buttons.append(
            [InlineKeyboardButton(f"Episode {ep_num}", callback_data=f"episode|{ep_num}|{ep_url}")]
        )

    reply_markup = InlineKeyboardMarkup(buttons)
    query.edit_message_text("Select an episode:", reply_markup=reply_markup)


def episode_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    _, ep_num, ep_url = query.data.split("|", maxsplit=2)

    msg = query.edit_message_text(
        f"🔄 Retrieving SUB HD-2 (1080p) link and English subtitle for Episode {ep_num}..."
    )

    try:
        hls_link, subtitle_url = extract_episode_stream_and_subtitle(ep_url)
    except Exception as e:
        logging.error(f"Error extracting data for {ep_url}: {e}", exc_info=True)
        query.edit_message_text(f"❌ Failed to extract data for Episode {ep_num}.")
        return

    if not hls_link:
        query.edit_message_text(
            f"😔 Could not find a SUB HD-2 (1080p) stream for Episode {ep_num}."
        )
        return

    text = (
        f"🎬 *Episode {ep_num}*\n\n"
        f"🔗 *1080p (SUB HD-2) HLS Link:*\n"
        f"`{hls_link}`\n\n"
    )

    if not subtitle_url:
        text += "❗ No English subtitle (.vtt) found.\n"
        query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)
        return

    try:
        local_vtt_path = download_and_rename_subtitle(
            subtitle_url, ep_num, cache_dir="subtitles_cache"
        )
    except Exception as e:
        logging.error(f"Error downloading/renaming subtitle: {e}", exc_info=True)
        text += "⚠️ Found an English subtitle URL but failed to download it."
        query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)
        return

    text += f"✅ English subtitle downloaded and renamed to `Episode {ep_num}.vtt`."
    query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)

    with open(local_vtt_path, "rb") as f:
        query.message.reply_document(
            document=InputFile(f, filename=f"Episode {ep_num}.vtt"),
            caption=f"Here is the subtitle for Episode {ep_num}.",
        )

    try:
        os.remove(local_vtt_path)
    except OSError:
        pass


def error_handler(update: object, context: CallbackContext):
    logging.error(msg="Exception while handling an update:", exc_info=context.error)
    if isinstance(update, Update) and update.callback_query:
        update.callback_query.message.reply_text("⚠️ Oops, something went wrong.")


def main():
    os.makedirs("subtitles_cache", exist_ok=True)

    # Launch health server in background (only if using “Web Service”)
    t = threading.Thread(target=run_health_server, daemon=True)
    t.start()

    updater = Updater(TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("search", search_command))

    dp.add_handler(CallbackQueryHandler(anime_callback, pattern=r"^anime:"))
    dp.add_handler(CallbackQueryHandler(episode_callback, pattern=r"^episode\|"))

    dp.add_error_handler(error_handler)

    logging.info("Bot started…")
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
