#!/usr/bin/env python3
# bot.py
from dotenv import load_dotenv
load_dotenv() 

import os
import threading
import logging
import asyncio
import time

from flask import Flask, request
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import Dispatcher, CommandHandler, CallbackQueryHandler, CallbackContext

from telethon import TelegramClient

from utils import (
    download_and_rename_subtitle,
    download_and_rename_video,
)

# ——————————————————————————————————————————————————————————————
# 1) Load environment variables
# ——————————————————————————————————————————————————————————————
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set")

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

TELETHON_API_ID = os.getenv("TELETHON_API_ID")
TELETHON_API_HASH = os.getenv("TELETHON_API_HASH")
if not TELETHON_API_ID or not TELETHON_API_HASH:
    raise RuntimeError(
        "TELETHON_API_ID and TELETHON_API_HASH environment variables must be set."
    )

# ——————————————————————————————————————————————————————————————
# 2) Initialize Bot API + Dispatcher
# ——————————————————————————————————————————————————————————————
bot = Bot(token=BOT_TOKEN)
dispatcher = Dispatcher(bot, None, workers=4, use_context=True)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ——————————————————————————————————————————————————————————————
# 3) In‐memory caches
# ——————————————————————————————————————————————————————————————
search_cache = {}           # chat_id → [ (title, slug), … ]
episode_cache = {}          # chat_id → [ (ep_num, episode_id), … ]
selected_anime_title = {}   # chat_id → title (so we can refer back to it)

# ——————————————————————————————————————————————————————————————
# 4) /start handler
# ——————————————————————————————————————————————————————————————
def start(update: Update, context: CallbackContext):
    welcome_text = (
        "🌸 *Hianime Downloader* 🌸\n\n"
        "🔍 *Find \\& Download Anime Episodes Directly*\n\n"
        "🎯 *What I Can Do:*\n"
        "• Search for your favorite anime on [hianimez\\.to](https://hianimez\\.to)\n"
        "• Download SUB\\-HD2 video as high\\-quality MP4\n"
        "• Include English subtitles \\(SRT/VTT\\)\n"
        "• Send everything as a document \\(no quality loss\\)\n\n"
        "📝 *How to Use:*\n"
        "1️⃣ `/search <anime name>` \\- Find anime titles\n"
        "2️⃣ Select the anime from the list of results\n"
        "3️⃣ Choose an episode to download \\(or tap \\\"Download All\\\"\\)\n"
        "4️⃣ Receive the high\\-quality MP4 \\+ subtitles automatically\n\n"
        "📩 *Contact @THe\\_vK\\_3 if any problem or Query* "
    )
    update.message.reply_text(
        welcome_text,
        parse_mode="MarkdownV2",
        disable_web_page_preview=True
    )

# ——————————————————————————————————————————————————————————————
# 5) /search handler
# ——————————————————————————————————————————————————————————————
def search_command(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id

    if len(context.args) == 0:
        update.message.reply_text("Please provide an anime name. Example:\n/search Naruto")
        return

    query_text = " ".join(context.args).strip()
    msg = update.message.reply_text(f"🔍 Searching for “{query_text}”…")

    try:
        from hianimez_scraper import search_anime
        results = search_anime(query_text)
    except Exception as e:
        logger.error(f"Search error: {e}", exc_info=True)
        msg.edit_text("❌ Search error; please try again later.")
        return

    if not results:
        msg.edit_text(f"No anime found matching “{query_text}.”")
        return

    # Store (title, slug) in search_cache
    search_cache[chat_id] = [(title, slug) for title, anime_url, slug in results]

    buttons = []
    for idx, (title, slug) in enumerate(search_cache[chat_id]):
        buttons.append([InlineKeyboardButton(title, callback_data=f"anime_idx:{idx}")])

    reply_markup = InlineKeyboardMarkup(buttons)
    try:
        msg.edit_text("Select the anime you want:", reply_markup=reply_markup)
    except Exception:
        pass

# ——————————————————————————————————————————————————————————————
# 6) Callback when user taps an anime button (store the title)
# ——————————————————————————————————————————————————————————————
def anime_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    chat_id = query.message.chat.id

    try:
        query.answer()
    except Exception:
        pass

    data = query.data  # e.g. "anime_idx:3"
    try:
        _, idx_str = data.split(":", maxsplit=1)
        idx = int(idx_str)
    except Exception:
        try:
            query.edit_message_text("❌ Internal error: invalid anime selection.")
        except Exception:
            pass
        return

    anime_list = search_cache.get(chat_id, [])
    if idx < 0 or idx >= len(anime_list):
        try:
            query.edit_message_text("❌ Internal error: anime index out of range.")
        except Exception:
            pass
        return

    title, slug = anime_list[idx]

    # STORE the selected anime’s title so we can reference it later
    selected_anime_title[chat_id] = title

    anime_url = f"https://hianimez.to/watch/{slug}"

    # Let the user know we’re fetching episodes:
    try:
        query.edit_message_text(
            f"🔍 Fetching episodes for *{title}*…", parse_mode="MarkdownV2"
        )
    except Exception:
        pass

    try:
        from hianimez_scraper import get_episodes_list
        episodes = get_episodes_list(anime_url)
    except Exception as e:
        logger.error(f"Error fetching episodes: {e}", exc_info=True)
        try:
            query.edit_message_text("❌ Failed to retrieve episodes for that anime.")
        except Exception:
            pass
        return

    if not episodes:
        try:
            query.edit_message_text("No episodes found for that anime.")
        except Exception:
            pass
        return

    # Store episodes in cache
    episode_cache[chat_id] = [(ep_num, ep_id) for ep_num, ep_id in episodes]

    # Build buttons: “Episode 1”, “Episode 2”, … + “Download All”
    buttons = []
    for i, (ep_num, ep_id) in enumerate(episode_cache[chat_id]):
        buttons.append([InlineKeyboardButton(f"Episode {ep_num}", callback_data=f"episode_idx:{i}")])
    buttons.append([InlineKeyboardButton("Download All", callback_data="episode_all")])

    reply_markup = InlineKeyboardMarkup(buttons)
    try:
        query.edit_message_text("Select an episode (or Download All):", reply_markup=reply_markup)
    except Exception:
        pass

# ──────────────────────────────────────────────────────────────────────────────
# 7a) Callback when user taps a single episode button (mention anime title)
# ──────────────────────────────────────────────────────────────────────────────
def episode_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    chat_id = query.message.chat.id

    try:
        query.answer()
    except Exception:
        pass

    data = query.data  # e.g. "episode_idx:5"
    try:
        _, idx_str = data.split(":", maxsplit=1)
        idx = int(idx_str)
    except Exception:
        try:
            query.edit_message_text("❌ Invalid episode selection.")
        except Exception:
            pass
        return

    ep_list = episode_cache.get(chat_id, [])
    if idx < 0 or idx >= len(ep_list):
        try:
            query.edit_message_text("❌ Episode index out of range.")
        except Exception:
            pass
        return

    ep_num, episode_id = ep_list[idx]

    # Fetch the stored anime name (if it exists)
    anime_name = selected_anime_title.get(chat_id)
    if anime_name:
        queued_text = (
            f"🔰*Details Of Anime*🔰\n\n"
            f"🎬 *Name:-* {anime_name} \n"
            f"🔢 *Episode:-* {ep_num}"
        )
    else:
        queued_text = f"⏳ Episode {ep_num} queued for download… You’ll receive it shortly."

    try:
        query.edit_message_text(queued_text, parse_mode="Markdown")
    except Exception:
        pass

    # Start a background thread for the heavy work (download → upload → subtitle)
    thread = threading.Thread(
        target=download_and_send_episode,
        args=(chat_id, ep_num, episode_id),
        daemon=True
    )
    thread.start()

    return

# ──────────────────────────────────────────────────────────────────────────────
# 7b) Callback when user taps “Download All” (mention anime title)
# ──────────────────────────────────────────────────────────────────────────────
def episodes_all_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    chat_id = query.message.chat.id

    try:
        query.answer()
    except Exception:
        pass

    ep_list = episode_cache.get(chat_id, [])
    if not ep_list:
        try:
            query.edit_message_text("❌ No episodes available to download.")
        except Exception:
            pass
        return

    # Fetch the stored anime name (if it exists)
    anime_name = selected_anime_title.get(chat_id)
    if anime_name:
        queued_all_text = (
            f"🔰*Details Of Anime*🔰\n\n"
            f"🎬 *Name:-* {anime_name} \n"
            f"🔢 *Episode:-* All "
        )
    else:
        queued_all_text = "⏳ Queued all episodes for download… You’ll receive them one by one."

    try:
        query.edit_message_text(queued_all_text, parse_mode="Markdown")
    except Exception:
        pass

    # Spawn a thread to handle downloading & sending all episodes
    thread = threading.Thread(
        target=download_and_send_all_episodes,
        args=(chat_id, ep_list),
        daemon=True
    )
    thread.start()

    return

# ──────────────────────────────────────────────────────────────────────────────
# Helper: Telethon upload with real‐time progress → send as “document”
# ──────────────────────────────────────────────────────────────────────────────
async def telethon_send_with_progress(chat_id: int, file_path: str, caption: str, status_message_id: int):
    """
    Uses Telethon (logged in as a Bot via bot_token) to send a single file (up to 2 GB)
    into `chat_id` as a document. Updates an existing Telegram message (status_message_id)
    with upload progress. Throttles edits to once every 3 seconds.
    """
    client = TelegramClient("telethon_bot_session", int(TELETHON_API_ID), TELETHON_API_HASH)
    try:
        await client.start(bot_token=BOT_TOKEN)

        total_bytes = os.path.getsize(file_path)
        start_time = time.time()
        last_upd = 0.0

        def progress_callback(uploaded_bytes: int, total_bytes_inner: int):
            nonlocal last_upd
            now = time.time()
            # Throttle to only every 3 seconds
            if now - last_upd < 3.0:
                return
            last_upd = now

            elapsed = now - start_time
            uploaded_mb = uploaded_bytes / (1024 * 1024)
            total_mb = total_bytes_inner / (1024 * 1024)
            speed = uploaded_mb / elapsed if elapsed > 0 else 0
            percent = (uploaded_bytes / total_bytes_inner) * 100 if total_bytes_inner > 0 else 0
            eta = (elapsed * (total_bytes_inner - uploaded_bytes) / uploaded_bytes) if uploaded_bytes > 0 else None

            elapsed_str = f"{int(elapsed//60)}m {int(elapsed%60)}s"
            eta_str = f"{int(eta//60)}m {int(eta%60)}s" if (eta is not None and eta >= 0) else "–"

            text = (
                "📤 Uploading File\n\n"
                f"📊Size: {uploaded_mb:.2f} MB of {total_mb:.2f} MB\n"
                f"⚡️Speed: {speed:.2f} MB/s\n"
                f"⏱️Time Elapsed: {elapsed_str}\n"
                f"⏳ETA: {eta_str}\n"
                f"📈Progress: {percent:.1f}%"
            )
            try:
                bot.edit_message_text(
                    text, chat_id=chat_id, message_id=status_message_id
                )
            except Exception:
                pass

        await client.send_file(
            entity=chat_id,
            file=file_path,
            caption=caption,
            force_document=True,
            progress_callback=progress_callback
        )
    except Exception as e:
        logger.error(f"[Telethon] Failed to send {file_path} to chat {chat_id}: {e}", exc_info=True)
    finally:
        await client.disconnect()

def send_file_via_telethon_with_progress(chat_id: int, file_path: str, caption: str, status_message_id: int):
    """
    Synchronous wrapper around `telethon_send_with_progress`.
    """
    try:
        asyncio.run(
            telethon_send_with_progress(
                chat_id=chat_id,
                file_path=file_path,
                caption=caption,
                status_message_id=status_message_id,
            )
        )
    except Exception as e:
        logger.error(f"[Telethon sync] Exception while sending {file_path} to chat {chat_id}: {e}", exc_info=True)

# ──────────────────────────────────────────────────────────────────────────────
# 9) Background task for sending a single episode (download → upload → subtitle, with deletions)
# ──────────────────────────────────────────────────────────────────────────────
def download_and_send_episode(chat_id: int, ep_num: str, episode_id: str):
    """
    1) Extract HLS link + subtitle URL.
    2) Download MP4 (report progress in a Telegram message, then delete it).
    3) Upload MP4 via Telethon (report progress in a Telegram message, then delete it).
    4) Send the subtitle (small file) via Bot API (report and delete that small status).
    """
    # (a) Step 1: Extract HLS + subtitle URL
    from hianimez_scraper import extract_episode_stream_and_subtitle
    try:
        hls_link, subtitle_url = extract_episode_stream_and_subtitle(episode_id)
    except Exception as e:
        logger.error(f"[Thread] Error extracting Episode {ep_num}: {e}", exc_info=True)
        bot.send_message(chat_id, f"❌ Failed to extract data for Episode {ep_num}.")
        return

    if not hls_link:
        bot.send_message(chat_id, f"😔 Could not find a SUB-HD2 video stream for Episode {ep_num}.")
        return

    # (b) Step 2: DOWNLOAD MP4 via ffmpeg (with progress callback throttled to 3s)
    status_download = bot.send_message(chat_id, "📥 Downloading File\nProgress: 0%")
    last_dl_update = [0.0]  # mutable container to track last update

    def download_progress_cb(downloaded_mb, total_duration_s, percent, speed_mb_s, elapsed_s, eta_s):
        now = time.time()
        # Throttle to only every 3 seconds
        if now - last_dl_update[0] < 3.0:
            return
        last_dl_update[0] = now

        elapsed_str = f"{int(elapsed_s//60)}m {int(elapsed_s%60)}s"
        eta_str = f"{int(eta_s//60)}m {int(eta_s%60)}s" if (eta_s is not None and eta_s >= 0) else "–"

        text = (
            "📥 Downloading File\n\n"
            f"📊Size: {downloaded_mb:.2f} MB\n"
            f"⚡️Speed: {speed_mb_s:.2f} MB/s\n"
            f"⏱️Time Elapsed: {elapsed_str}\n"
            f"⏳ETA: {eta_str}\n"
            f"📈Progress: {percent:.1f}%"
        )
        try:
            bot.edit_message_text(text, chat_id=chat_id, message_id=status_download.message_id)
        except Exception:
            pass

    try:
        raw_mp4 = download_and_rename_video(
            hls_link,
            ep_num,
            cache_dir="videos_cache",
            progress_callback=download_progress_cb
        )
    except Exception as e:
        logger.error(f"[Thread] Error downloading video (Episode {ep_num}): {e}", exc_info=True)
        # Delete the “Downloading File” status message
        try:
            bot.delete_message(chat_id=chat_id, message_id=status_download.message_id)
        except Exception:
            pass

        # Fallback: send HLS link + subtitle
        bot.send_message(
            chat_id,
            f"⚠️ Failed to convert Episode {ep_num} to MP4. Here’s the HLS link instead:\n\n{hls_link}"
        )
        if subtitle_url:
            try:
                local_vtt = download_and_rename_subtitle(subtitle_url, ep_num, cache_dir="subtitles_cache")
                status_sub = bot.send_message(chat_id, f"✅ Subtitle downloaded as “Episode {ep_num}.vtt”.")
                bot.send_document(
                    chat_id=chat_id,
                    document=InputFile(open(local_vtt, "rb"), filename=f"Episode {ep_num}.vtt"),
                    caption=f"Here is the subtitle for Episode {ep_num}.",
                )
                os.remove(local_vtt)
                # Delete subtitle‐status message
                try:
                    bot.delete_message(chat_id=chat_id, message_id=status_sub.message_id)
                except Exception:
                    pass
            except Exception as se:
                logger.error(f"[Thread] Error sending subtitle (Episode {ep_num}): {se}", exc_info=True)
                bot.send_message(chat_id, f"⚠️ Could not download/send subtitle for Episode {ep_num}.")
        return

    # Delete the “Downloading File” status message (100% download done)
    try:
        bot.delete_message(chat_id=chat_id, message_id=status_download.message_id)
    except Exception:
        pass

    # (c) Step 3: UPLOAD MP4 via Telethon (with progress callback throttled to 3s)
    status_upload = bot.send_message(chat_id, "📤 Uploading File\nProgress: 0%")
    try:
        send_file_via_telethon_with_progress(
            chat_id=chat_id,
            file_path=raw_mp4,
            caption=f"Episode {ep_num}.mp4",
            status_message_id=status_upload.message_id
        )
    except Exception as e:
        logger.error(f"[Thread] Telethon upload failed for Episode {ep_num}: {e}", exc_info=True)
        # Delete the upload status (if it exists)
        try:
            bot.delete_message(chat_id=chat_id, message_id=status_upload.message_id)
        except Exception:
            pass

        # Fallback: send HLS link + subtitle
        bot.send_message(chat_id, f"⚠️ Could not send Episode {ep_num} via Telethon. Here’s the HLS link:\n\n{hls_link}")
        try:
            os.remove(raw_mp4)
        except OSError:
            pass

        if subtitle_url:
            try:
                local_vtt = download_and_rename_subtitle(subtitle_url, ep_num, cache_dir="subtitles_cache")
                status_sub = bot.send_message(chat_id, f"✅ Subtitle downloaded as “Episode {ep_num}.vtt.”")
                bot.send_document(
                    chat_id=chat_id,
                    document=InputFile(open(local_vtt, "rb"), filename=f"Episode {ep_num}.vtt"),
                    caption=f"Here is the subtitle for Episode {ep_num}."
                )
                os.remove(local_vtt)
                # Delete subtitle‐status message
                try:
                    bot.delete_message(chat_id=chat_id, message_id=status_sub.message_id)
                except Exception:
                    pass
            except Exception as se:
                logger.error(f"[Thread] Error sending subtitle (Episode {ep_num}): {se}", exc_info=True)
                bot.send_message(chat_id, f"⚠️ Could not download/send subtitle for Episode {ep_num}.")
        return
    finally:
        # Clean up the raw MP4 from disk once Telethon is done
        try:
            os.remove(raw_mp4)
        except OSError:
            pass

    # Delete the “Uploading File” status message (100% upload done)
    try:
        bot.delete_message(chat_id=chat_id, message_id=status_upload.message_id)
    except Exception:
        pass

    # (d) Step 4: Send subtitle via Bot API (small file)
    if not subtitle_url:
        bot.send_message(chat_id, "❗ No English subtitle (.vtt) found.")
        return

    try:
        local_vtt = download_and_rename_subtitle(subtitle_url, ep_num, cache_dir="subtitles_cache")
    except Exception as e:
        logger.error(f"[Thread] Error downloading subtitle (Episode {ep_num}): {e}", exc_info=True)
        bot.send_message(chat_id, f"⚠️ Found a subtitle URL but failed to download for Episode {ep_num}.")
        return

    status_sub = bot.send_message(chat_id, f"✅ Subtitle downloaded as “Episode {ep_num}.vtt.”")
    try:
        bot.send_document(
            chat_id=chat_id,
            document=InputFile(open(local_vtt, "rb"), filename=f"Episode {ep_num}.vtt"),
            caption=f"Here is the subtitle for Episode {ep_num}."
        )
    except Exception as e:
        logger.error(f"[Thread] Error sending subtitle (Episode {ep_num}): {e}", exc_info=True)
        bot.send_message(chat_id, f"⚠️ Could not send subtitle for Episode {ep_num}.")
    finally:
        try:
            os.remove(local_vtt)
        except OSError:
            pass

    # Delete the subtitle‐status message after sending
    try:
        bot.delete_message(chat_id=chat_id, message_id=status_sub.message_id)
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# 10) Background task for “Download All” episodes (download→upload→subtitle with deletions)
# ──────────────────────────────────────────────────────────────────────────────
def download_and_send_all_episodes(chat_id: int, ep_list: list):
    """
    Loops through each (ep_num, episode_id):
      1) Extract HLS + subtitle
      2) Download MP4 (real‐time progress throttled to 3s)
      3) Upload MP4 via Telethon (real‐time progress throttled to 3s)
      4) Send subtitle via Bot API
      5) Delete status messages after each step
      6) If any step fails, fallback to sending HLS link + subtitle
    """
    from hianimez_scraper import extract_episode_stream_and_subtitle

    for ep_num, episode_id in ep_list:
        # (a) Extract HLS + subtitle
        try:
            hls_link, subtitle_url = extract_episode_stream_and_subtitle(episode_id)
        except Exception as e:
            logger.error(f"[Thread] Error extracting Episode {ep_num}: {e}", exc_info=True)
            bot.send_message(chat_id, f"❌ Failed to extract data for Episode {ep_num}. Skipping.")
            continue

        if not hls_link:
            bot.send_message(chat_id, f"😔 Episode {ep_num}: No SUB-HD2 stream found. Skipping.")
            continue

        # (b) Download raw MP4 (throttled to 3 seconds)
        status_download = bot.send_message(chat_id, f"📥 Downloading Episode {ep_num}...\nProgress: 0%")
        last_dl_update = [0.0]

        def download_progress_cb(downloaded_mb, total_duration_s, percent, speed_mb_s, elapsed_s, eta_s):
            now = time.time()
            if now - last_dl_update[0] < 3.0:
                return
            last_dl_update[0] = now

            elapsed_str = f"{int(elapsed_s//60)}m {int(elapsed_s%60)}s"
            eta_str = f"{int(eta_s//60)}m {int(eta_s%60)}s" if (eta_s is not None and eta_s >= 0) else "–"
            text = (
                f"📥 Downloading Episode {ep_num}\n"
                f"📊Size: {downloaded_mb:.2f} MB\n"
                f"⚡️Speed: {speed_mb_s:.2f} MB/s\n"
                f"⏱️Time Elapsed: {elapsed_str}\n"
                f"⏳ETA: {eta_str}\n"
                f"📈Progress: {percent:.1f}%"
            )
            try:
                bot.edit_message_text(text, chat_id=chat_id, message_id=status_download.message_id)
            except Exception:
                pass

        try:
            raw_mp4 = download_and_rename_video(
                hls_link,
                ep_num,
                cache_dir="videos_cache",
                progress_callback=download_progress_cb
            )
        except Exception as e:
            logger.error(f"[Thread] Error downloading Episode {ep_num}: {e}", exc_info=True)
            try:
                bot.delete_message(chat_id=chat_id, message_id=status_download.message_id)
            except Exception:
                pass

            # Fallback: send HLS link + subtitle
            bot.send_message(
                chat_id,
                f"⚠️ Could not convert Episode {ep_num} to MP4. Here’s the HLS link:\n\n{hls_link}"
            )
            if subtitle_url:
                try:
                    local_vtt = download_and_rename_subtitle(subtitle_url, ep_num, cache_dir="subtitles_cache")
                    status_sub = bot.send_message(chat_id, f"✅ Subtitle downloaded as “Episode {ep_num}.vtt.”")
                    bot.send_document(
                        chat_id=chat_id,
                        document=InputFile(open(local_vtt, "rb"), filename=f"Episode {ep_num}.vtt"),
                        caption=f"Here is the subtitle for Episode {ep_num}."
                    )
                    os.remove(local_vtt)
                    try:
                        bot.delete_message(chat_id=chat_id, message_id=status_sub.message_id)
                    except Exception:
                        pass
                except Exception as se:
                    logger.error(f"[Thread] Error sending subtitle (Episode {ep_num}): {se}", exc_info=True)
                    bot.send_message(chat_id, f"⚠️ Could not send subtitle for Episode {ep_num}.")
            continue

        # Delete the “Downloading Episode…” status message
        try:
            bot.delete_message(chat_id=chat_id, message_id=status_download.message_id)
        except Exception:
            pass

        # (c) Upload via Telethon (throttled to 3 seconds)
        status_upload = bot.send_message(chat_id, f"📤 Uploading Episode {ep_num}...\nProgress: 0%")
        try:
            send_file_via_telethon_with_progress(
                chat_id=chat_id,
                file_path=raw_mp4,
                caption=f"Episode {ep_num}.mp4",
                status_message_id=status_upload.message_id
            )
        except Exception as e:
            logger.error(f"[Thread] Telethon upload failed for Episode {ep_num}: {e}", exc_info=True)
            try:
                bot.delete_message(chat_id=chat_id, message_id=status_upload.message_id)
            except Exception:
                pass

            # Fallback: send HLS link + subtitle
            bot.send_message(chat_id, f"⚠️ Could not send Episode {ep_num} via Telethon. Here’s the HLS link:\n\n{hls_link}")
            try:
                os.remove(raw_mp4)
            except OSError:
                pass
            if subtitle_url:
                try:
                    local_vtt = download_and_rename_subtitle(subtitle_url, ep_num, cache_dir="subtitles_cache")
                    status_sub = bot.send_message(chat_id, f"✅ Subtitle downloaded as “Episode {ep_num}.vtt.”")
                    bot.send_document(
                        chat_id=chat_id,
                        document=InputFile(open(local_vtt, "rb"), filename=f"Episode {ep_num}.vtt"),
                        caption=f"Here is the subtitle for Episode {ep_num}."
                    )
                    os.remove(local_vtt)
                    try:
                        bot.delete_message(chat_id=chat_id, message_id=status_sub.message_id)
                    except Exception:
                        pass
                except Exception as se:
                    logger.error(f"[Thread] Error sending subtitle (Episode {ep_num}): {se}", exc_info=True)
                    bot.send_message(chat_id, f"⚠️ Could not send subtitle for Episode {ep_num}.")
            continue
        finally:
            # Clean up raw MP4
            try:
                os.remove(raw_mp4)
            except OSError:
                pass

        # Delete the “Uploading Episode…” status message
        try:
            bot.delete_message(chat_id=chat_id, message_id=status_upload.message_id)
        except Exception:
            pass

        # (d) Send subtitle
        if not subtitle_url:
            bot.send_message(chat_id, f"❗ No English subtitle found for Episode {ep_num}.")
            continue

        try:
            local_vtt = download_and_rename_subtitle(subtitle_url, ep_num, cache_dir="subtitles_cache")
        except Exception as e:
            logger.error(f"[Thread] Error downloading subtitle (Episode {ep_num}): {e}", exc_info=True)
            bot.send_message(chat_id, f"⚠️ Could not download subtitle for Episode {ep_num}.")
            continue

        status_sub = bot.send_message(chat_id, f"✅ Subtitle downloaded as “Episode {ep_num}.vtt.”")
        try:
            bot.send_document(
                chat_id=chat_id,
                document=InputFile(open(local_vtt, "rb"), filename=f"Episode {ep_num}.vtt"),
                caption=f"Here is the subtitle for Episode {ep_num}."
            )
        except Exception as e:
            logger.error(f"[Thread] Error sending subtitle (Episode {ep_num}): {e}", exc_info=True)
            bot.send_message(chat_id, f"⚠️ Could not send subtitle for Episode {ep_num}.")
        finally:
            try:
                os.remove(local_vtt)
            except OSError:
                pass

        # Delete the subtitle‐status message
        try:
            bot.delete_message(chat_id=chat_id, message_id=status_sub.message_id)
        except Exception:
            pass

# ──────────────────────────────────────────────────────────────────────────────
# 11) Error handler
# ──────────────────────────────────────────────────────────────────────────────
def error_handler(update: object, context: CallbackContext):
    logger.error("Exception while handling an update:", exc_info=context.error)
    if isinstance(update, Update) and update.callback_query:
        try:
            update.callback_query.message.reply_text("⚠️ Oops, something went wrong.")
        except Exception:
            pass

# ──────────────────────────────────────────────────────────────────────────────
# 12) Register handlers with the dispatcher
# ──────────────────────────────────────────────────────────────────────────────
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("search", search_command))
dispatcher.add_handler(CallbackQueryHandler(anime_callback, pattern=r"^anime_idx:"))
dispatcher.add_handler(CallbackQueryHandler(episode_callback, pattern=r"^episode_idx:"))
dispatcher.add_handler(CallbackQueryHandler(episodes_all_callback, pattern=r"^episode_all$"))
dispatcher.add_error_handler(error_handler)

# ──────────────────────────────────────────────────────────────────────────────
# 13) Flask app for webhook + health check
# ──────────────────────────────────────────────────────────────────────────────
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

# ──────────────────────────────────────────────────────────────────────────────
# 14) On startup, set Telegram webhook to <KOYEB_APP_URL>/webhook
# ──────────────────────────────────────────────────────────────────────────────
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
