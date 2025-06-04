#!/usr/bin/env python3
# bot.py

import os
import logging
import telegram
from flask import Flask, request
from telegram import (
    Bot,
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
)
from telegram.ext import Dispatcher, CommandHandler, CallbackQueryHandler, CallbackContext

from hianimez_scraper import (
    search_anime,
    get_episodes_list,
    extract_episode_stream_and_subtitle,
)
from utils import download_and_rename_subtitle, download_and_rename_video

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
# 3) In‐memory caches for search results & episode lists per chat
# ——————————————————————————————————————————————————————————————
search_cache = {}   # chat_id → [ (title, slug), … ]
episode_cache = {}  # chat_id → [ (ep_num, episode_id), … ]

# ——————————————————————————————————————————————————————————————
# 4) /start handler
# ——————————————————————————————————————————————————————————————
def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "👋 Hello! I can help you search for anime on hianimez.to and\n"
        " extract the SUB-HD2 Video (as an MP4) + English subtitles.\n\n"
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
        buttons.append([InlineKeyboardButton(title, callback_data=f"anime_idx:{idx}")])

    reply_markup = InlineKeyboardMarkup(buttons)
    msg.edit_text("Select the anime you want:", reply_markup=reply_markup)

# ——————————————————————————————————————————————————————————————
# 6) Callback when user taps an anime button (anime_idx)
# ——————————————————————————————————————————————————————————————
def anime_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    # Acknowledge immediately
    try:
        query.answer()
    except telegram.error.BadRequest:
        pass

    chat_id = query.message.chat.id
    data = query.data  # e.g. "anime_idx:3"
    try:
        _, idx_str = data.split(":", maxsplit=1)
        idx = int(idx_str)
    except Exception:
        query.edit_message_text("❌ Internal error: invalid anime selection.")
        return

    anime_list = search_cache.get(chat_id, [])
    if idx < 0 or idx >= len(anime_list):
        query.edit_message_text("❌ Internal error: anime index out of range.")
        return

    title, slug = anime_list[idx]
    anime_url = f"https://hianimez.to/watch/{slug}"

    msg = query.edit_message_text(
        f"🔍 Fetching episodes for *{title}*…", parse_mode="MarkdownV2"
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

    # Store (ep_num, episode_id) in episode_cache[chat_id]
    episode_cache[chat_id] = []
    for ep_num, ep_id in episodes:
        episode_cache[chat_id].append((ep_num, ep_id))

    # Build buttons for each episode
    buttons = []
    for i, (ep_num, ep_id) in enumerate(episode_cache[chat_id]):
        buttons.append([InlineKeyboardButton(f"Episode {ep_num}", callback_data=f"episode_idx:{i}")])

    # Add one final row for "Download All"
    buttons.append([InlineKeyboardButton("Download All", callback_data="episode_all")])

    reply_markup = InlineKeyboardMarkup(buttons)
    query.edit_message_text("Select an episode (or Download All):", reply_markup=reply_markup)

# ──────────────────────────────────────────────────────────────────────────────
# 7a) Callback when user taps a single episode button (episode_idx)
# ──────────────────────────────────────────────────────────────────────────────
def episode_callback(update: Update, context: CallbackContext):
    query = update.callback_query

    # 1) Acknowledge right away (before any slow processing)
    try:
        query.answer()
    except telegram.error.BadRequest:
        pass

    chat_id = query.message.chat.id
    data = query.data  # e.g. "episode_idx:5"
    try:
        _, idx_str = data.split(":", maxsplit=1)
        idx = int(idx_str)
    except Exception:
        query.edit_message_text("❌ Internal error: invalid episode selection.")
        return

    ep_list = episode_cache.get(chat_id, [])
    if idx < 0 or idx >= len(ep_list):
        query.edit_message_text("❌ Internal error: episode index out of range.")
        return

    ep_num, episode_id = ep_list[idx]

    # 2) Let the user know we are working on it
    query.edit_message_text(f"🔄 Retrieving Episode {ep_num} (SUB-HD2 Video + subtitle)…")

    # 3) Extract HLS link + subtitle URL
    try:
        hls_link, subtitle_url = extract_episode_stream_and_subtitle(episode_id)
    except Exception as e:
        logger.error(f"Error extracting episode data: {e}", exc_info=True)
        query.edit_message_text(f"❌ Failed to extract data for Episode {ep_num}.")
        return

    if not hls_link:
        query.edit_message_text(f"😔 Could not find a SUB-HD2 Video stream for Episode {ep_num}.")
        return

    # 4) Download the actual MP4 from the HLS link
    try:
        local_mp4 = download_and_rename_video(hls_link, ep_num, cache_dir="videos_cache")
    except Exception as e:
        logger.error(f"Error downloading video: {e}", exc_info=True)
        # Fallback: send HLS link instead of MP4
        text = (
            f"⚠️ Failed to download video for Episode {ep_num}. Here's the HLS link instead:\n\n"
            f"{hls_link}"
        )
        query.message.reply_text(text)

        # If there is a subtitle, try sending it
        if subtitle_url:
            try:
                local_vtt = download_and_rename_subtitle(subtitle_url, ep_num, cache_dir="subtitles_cache")
                query.message.reply_text(f"✅ Subtitle downloaded as \"Episode {ep_num}.vtt\".")
                with open(local_vtt, "rb") as f:
                    query.message.reply_document(
                        document=InputFile(f, filename=f"Episode {ep_num}.vtt"),
                        caption=f"Here is the subtitle for Episode {ep_num}.",
                    )
                os.remove(local_vtt)
            except Exception as se:
                logger.error(f"Error downloading subtitle: {se}", exc_info=True)
                query.message.reply_text("⚠️ Found a subtitle URL, but failed to download it.")
        return

    # 5) Send the downloaded MP4 as a Document
    query.message.reply_text(f"✅ Video for Episode {ep_num} downloaded. Sending now…")
    try:
        with open(local_mp4, "rb") as vid_f:
            query.message.reply_document(
                document=InputFile(vid_f, filename=f"Episode {ep_num}.mp4"),
                caption=f"Here is the full video for Episode {ep_num}.",
            )
    except Exception as e:
        logger.error(f"Error sending video file: {e}", exc_info=True)
        query.message.reply_text(f"⚠️ Could not send the video file for Episode {ep_num}.")
    finally:
        try:
            os.remove(local_mp4)
        except OSError:
            pass

    # 6) Download & send subtitle if it exists
    if not subtitle_url:
        query.message.reply_text("❗ No English subtitle (.vtt) found.")
        return

    try:
        local_vtt = download_and_rename_subtitle(subtitle_url, ep_num, cache_dir="subtitles_cache")
    except Exception as e:
        logger.error(f"Error downloading subtitle: {e}", exc_info=True)
        query.message.reply_text("⚠️ Found a subtitle URL, but failed to download it.")
        return

    query.message.reply_text(f"✅ English subtitle downloaded as \"Episode {ep_num}.vtt\".")
    with open(local_vtt, "rb") as f:
        query.message.reply_document(
            document=InputFile(f, filename=f"Episode {ep_num}.vtt"),
            caption=f"Here is the subtitle for Episode {ep_num}.",
        )
    try:
        os.remove(local_vtt)
    except OSError:
        pass

# ──────────────────────────────────────────────────────────────────────────────
# 7b) Callback when user taps "Download All" (episode_all)
# ──────────────────────────────────────────────────────────────────────────────
def episodes_all_callback(update: Update, context: CallbackContext):
    query = update.callback_query

    # 1) Acknowledge right away
    try:
        query.answer()
    except telegram.error.BadRequest:
        pass

    chat_id = query.message.chat.id

    ep_list = episode_cache.get(chat_id, [])
    if not ep_list:
        query.edit_message_text("❌ No episodes available to download.")
        return

    # 2) Inform user that all downloads are starting
    query.edit_message_text(
        "🔄 Downloading all episodes (SUB-HD2 Video + subtitle)… This may take a while."
    )

    # 3) Loop through each episode
    for ep_num, episode_id in ep_list:
        # a) Extract HLS link + subtitle URL
        try:
            hls_link, subtitle_url = extract_episode_stream_and_subtitle(episode_id)
        except Exception as e:
            logger.error(f"Error extracting episode {ep_num}: {e}", exc_info=True)
            bot.send_message(chat_id, f"❌ Failed to extract data for Episode {ep_num}. Skipping.")
            continue

        if not hls_link:
            bot.send_message(chat_id, f"😔 Episode {ep_num}: No SUB-HD2 Video stream found. Skipping.")
            continue

        # b) Attempt to download the MP4
        try:
            local_mp4 = download_and_rename_video(hls_link, ep_num, cache_dir="videos_cache")
        except Exception as e:
            logger.error(f"Error downloading video for Episode {ep_num}: {e}", exc_info=True)
            bot.send_message(
                chat_id,
                f"⚠️ Could not download video for Episode {ep_num}. Here's the HLS link instead:\n\n{hls_link}"
            )
            # Still try to send subtitle if present
            if subtitle_url:
                try:
                    local_vtt = download_and_rename_subtitle(subtitle_url, ep_num, cache_dir="subtitles_cache")
                    bot.send_message(chat_id, f"✅ Subtitle downloaded as \"Episode {ep_num}.vtt\".")
                    bot.send_document(
                        chat_id=chat_id,
                        document=InputFile(open(local_vtt, "rb"), filename=f"Episode {ep_num}.vtt"),
                        caption=f"Subtitle for Episode {ep_num}"
                    )
                    os.remove(local_vtt)
                except Exception as se:
                    logger.error(f"Error sending subtitle for Episode {ep_num}: {se}", exc_info=True)
                    bot.send_message(chat_id, f"⚠️ Could not send subtitle for Episode {ep_num}.")
            continue

        # c) Send the downloaded MP4
        bot.send_message(chat_id, f"✅ Downloaded Episode {ep_num}. Sending video file…")
        try:
            with open(local_mp4, "rb") as vid_f:
                bot.send_document(
                    chat_id=chat_id,
                    document=InputFile(vid_f, filename=f"Episode {ep_num}.mp4"),
                    caption=f"Here is Episode {ep_num}."
                )
        except Exception as e:
            logger.error(f"Error sending video for Episode {ep_num}: {e}", exc_info=True)
            bot.send_message(chat_id, f"⚠️ Could not send video file for Episode {ep_num}.")
        finally:
            try:
                os.remove(local_mp4)
            except OSError:
                pass

        # d) Download & send subtitle if it exists
        if not subtitle_url:
            bot.send_message(chat_id, f"❗ No English subtitle (.vtt) found for Episode {ep_num}.")
            continue

        try:
            local_vtt = download_and_rename_subtitle(subtitle_url, ep_num, cache_dir="subtitles_cache")
        except Exception as e:
            logger.error(f"Error downloading subtitle for Episode {ep_num}: {e}", exc_info=True)
            bot.send_message(chat_id, f"⚠️ Found a subtitle URL for Episode {ep_num}, but failed to download it.")
            continue

        bot.send_message(chat_id, f"✅ Subtitle for Episode {ep_num} downloaded as \"Episode {ep_num}.vtt\".")
        try:
            with open(local_vtt, "rb") as sub_f:
                bot.send_document(
                    chat_id=chat_id,
                    document=InputFile(sub_f, filename=f"Episode {ep_num}.vtt"),
                    caption=f"Subtitle for Episode {ep_num}"
                )
        except Exception as e:
            logger.error(f"Error sending subtitle for Episode {ep_num}: {e}", exc_info=True)
            bot.send_message(chat_id, f"⚠️ Could not send subtitle file for Episode {ep_num}.")
        finally:
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
        try:
            update.callback_query.message.reply_text("⚠️ Oops, something went wrong.")
        except Exception:
            pass

# ——————————————————————————————————————————————————————————————
# 9) Register handlers with the dispatcher
# ——————————————————————————————————————————————————————————————
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("search", search_command))
dispatcher.add_handler(CallbackQueryHandler(anime_callback, pattern=r"^anime_idx:"))
dispatcher.add_handler(CallbackQueryHandler(episode_callback, pattern=r"^episode_idx:"))
dispatcher.add_handler(CallbackQueryHandler(episodes_all_callback, pattern=r"^episode_all$"))
dispatcher.add_error_handler(error_handler)

# ——————————————————————————————————————————————————————————————
# 10) Flask app for webhook + health check
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
# 11) On startup, set Telegram webhook to <KOYEB_APP_URL>/webhook
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
    os.makedirs("videos_cache", exist_ok=True)
    logger.info("Starting Flask server on port 8080…")
    app.run(host="0.0.0.0", port=8080)
