#!/usr/bin/env python3
# bot.py

import os
import threading
import logging
import asyncio
import time

from dotenv import load_dotenv
load_dotenv()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext

from telethon import TelegramClient

from utils import (
    download_and_rename_subtitle,
    download_and_rename_video,
)

# ——————————————————————————————————————————————————————————————
# 0) ALLOW‐LIST CONFIGURATION
# ——————————————————————————————————————————————————————————————
ALLOWED_USERS = {
    1423807625,
    5476335536,
    2096201372,
    633599652,
    # Add additional Telegram user IDs here as needed.
}

DENIED_MESSAGE = (
    "🚫 *Access Denied\\!*  \n"
    "You are not authorized to use this bot\\.  \n\n"
    "📩 Contact @THe\\_vK\\_3 for access\\!"
)

# ——————————————————————————————————————————————————————————————
# 1) Load environment variables
# ——————————————————————————————————————————————————————————————
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set")

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
# 2) Set up logging
# ——————————————————————————————————————————————————————————————
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ——————————————————————————————————————————————————————————————
# 3) In‐memory caches (per-chat)
# ——————————————————————————————————————————————————————————————
search_cache = {}           # chat_id → [ (title, slug), … ]
episode_cache = {}          # chat_id → [ (ep_num, episode_id), … ]
selected_anime_title = {}   # chat_id → title (for display)

# ——————————————————————————————————————————————————————————————
# 4) Cancellation events (per-chat)
# ——————————————————————————————————————————————————————————————
cancel_events = {}          # chat_id → threading.Event()

# ——————————————————————————————————————————————————————————————
# 5) /start handler
# ——————————————————————————————————————————————————————————————
def start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    # Deny access if user not in ALLOWED_USERS
    if user_id not in ALLOWED_USERS:
        update.message.reply_text(
            DENIED_MESSAGE,
            parse_mode="MarkdownV2",
            disable_web_page_preview=True
        )
        return

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
        "☑️ Send `/cancel` at any time to abort an ongoing download\n\n"
        "📩 *Contact @THe\\_vK\\_3 if any problem or Query* "
    )
    update.message.reply_text(
        welcome_text,
        parse_mode="MarkdownV2",
        disable_web_page_preview=True
    )

# ——————————————————————————————————————————————————————————————
# 6) /search handler
# ——————————————————————————————————————————————————————————————
def search_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if user_id not in ALLOWED_USERS:
        update.message.reply_text(
            DENIED_MESSAGE,
            parse_mode="MarkdownV2",
            disable_web_page_preview=True
        )
        return

    if len(context.args) == 0:
        update.message.reply_text("⚠️ Please provide an anime name.\nExample: /search Naruto")
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
# 7) Callback when user taps an anime button (store the title)
# ——————————————————————————————————————————————————————————————
def anime_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat.id

    if user_id not in ALLOWED_USERS:
        query.answer()
        query.message.reply_text(
            DENIED_MESSAGE,
            parse_mode="MarkdownV2",
            disable_web_page_preview=True
        )
        return

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
    selected_anime_title[chat_id] = title
    anime_url = f"https://hianimez.to/watch/{slug}"

    # Inform user we’re fetching episodes
    try:
        title_escaped = (
            title
            .replace("_", "\\_")
            .replace(".", "\\.")
            .replace("(", "\\(")
            .replace(")", "\\)")
            .replace("-", "\\-")
        )
        query.edit_message_text(
            f"🔍 Fetching episodes for *{title_escaped}*…",
            parse_mode="MarkdownV2"
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
# 8a) Callback when user taps a single episode button
# ──────────────────────────────────────────────────────────────────────────────
def episode_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat.id

    if user_id not in ALLOWED_USERS:
        query.answer()
        query.message.reply_text(
            DENIED_MESSAGE,
            parse_mode="MarkdownV2",
            disable_web_page_preview=True
        )
        return

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

    anime_name = selected_anime_title.get(chat_id)
    if anime_name:
        safe_name = (
            anime_name
            .replace("_", "\\_")
            .replace(".", "\\.")
            .replace("(", "\\(")
            .replace(")", "\\)")
            .replace("-", "\\-")
        )
        details_text = (
            "🔰 *Details Of Anime* 🔰\n\n"
            "🎬 *Name:* " + safe_name + "\n"
            "🔢 *Episode:* " + str(ep_num)
        )
        try:
            query.edit_message_text(details_text, parse_mode="MarkdownV2")
        except Exception:
            fallback = f"Details Of Anime:\nName: {anime_name}\nEpisode: {ep_num}"
            try:
                query.edit_message_text(fallback)
            except Exception:
                pass
    else:
        queued_text = f"⏳ Episode {ep_num} queued for download… You’ll receive it shortly."
        try:
            query.edit_message_text(queued_text)
        except Exception:
            pass

    # Reset (or create) the cancel event for this chat
    cancel_events[chat_id] = threading.Event()

    # Start a background thread for download → upload → subtitle
    thread = threading.Thread(
        target=download_and_send_episode,
        args=(chat_id, ep_num, episode_id),
        daemon=True
    )
    thread.start()

# ──────────────────────────────────────────────────────────────────────────────
# 8b) Callback when user taps “Download All”
# ──────────────────────────────────────────────────────────────────────────────
def episodes_all_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat.id

    if user_id not in ALLOWED_USERS:
        query.answer()
        query.message.reply_text(
            DENIED_MESSAGE,
            parse_mode="MarkdownV2",
            disable_web_page_preview=True
        )
        return

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

    anime_name = selected_anime_title.get(chat_id)
    if anime_name:
        safe_name = (
            anime_name
            .replace("_", "\\_")
            .replace(".", "\\.")
            .replace("(", "\\(")
            .replace(")", "\\)")
            .replace("-", "\\-")
        )
        all_text = (
            "🔰 *Details Of Anime* 🔰\n\n"
            "🎬 *Name:* " + safe_name + "\n"
            "🔢 *Episode:* All"
        )
        try:
            query.edit_message_text(all_text, parse_mode="MarkdownV2")
        except Exception:
            fallback = f"Details Of Anime:\nName: {anime_name}\nEpisode: All"
            try:
                query.edit_message_text(fallback)
            except Exception:
                pass
    else:
        queued_all_text = "⏳ Queued all episodes for download… You’ll receive them one by one."
        try:
            query.edit_message_text(queued_all_text)
        except Exception:
            pass

    # Reset (or create) the cancel event for this chat
    cancel_events[chat_id] = threading.Event()

    thread = threading.Thread(
        target=download_and_send_all_episodes,
        args=(chat_id, ep_list),
        daemon=True
    )
    thread.start()

# ──────────────────────────────────────────────────────────────────────────────
# 9) /cancel handler
# ──────────────────────────────────────────────────────────────────────────────
def cancel_command(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    event = cancel_events.get(chat_id)
    if event:
        event.set()
        update.message.reply_text("❌ All ongoing operations have been cancelled.")
    else:
        update.message.reply_text("ℹ️ There was nothing to cancel.")

# ──────────────────────────────────────────────────────────────────────────────
# 10) Helper: Telethon upload with real‐time progress → send as “document”
# ──────────────────────────────────────────────────────────────────────────────
async def telethon_send_with_progress(chat_id: int, file_path: str, caption: str, status_message_id: int):
    """
    Uses Telethon to send a single file (up to 2 GB) into `chat_id` as a document.
    Updates an existing Telegram message (status_message_id) with upload progress.
    This uses a per-chat session file: telethon_bot_session_{chat_id}.
    """
    session_name = f"telethon_bot_session_{chat_id}"
    client = TelegramClient(session_name, int(TELETHON_API_ID), TELETHON_API_HASH)
    try:
        await client.start(bot_token=BOT_TOKEN)

        total_bytes = os.path.getsize(file_path)
        start_time = time.time()
        last_upd = 0.0

        def progress_callback(uploaded_bytes: int, total_bytes_inner: int):
            nonlocal last_upd
            now = time.time()
            if now - last_upd < 3.0:
                return
            last_upd = now

            elapsed = now - start_time
            uploaded_mb = uploaded_bytes / (1024 * 1024)
            total_mb = total_bytes_inner / (1024 * 1024)
            speed = uploaded_mb / elapsed if elapsed > 0 else 0
            percent = (uploaded_bytes / total_bytes_inner) * 100 if total_bytes_inner > 0 else 0
            eta = (
                (elapsed * (total_bytes_inner - uploaded_bytes) / uploaded_bytes)
                if uploaded_bytes > 0
                else None
            )

            elapsed_str = f"{int(elapsed//60)}m {int(elapsed%60)}s"
            eta_str = (
                f"{int(eta//60)}m {int(eta%60)}s"
                if (eta is not None and eta >= 0)
                else "–"
            )

            text = (
                "📤 <b>Uploading File</b>\n\n"
                f"📊Size: {uploaded_mb:.2f} MB of {total_mb:.2f} MB\n"
                f"⚡️Speed: {speed:.2f} MB/s\n"
                f"⏱️Time Elapsed: {elapsed_str}\n"
                f"⏳ETA: {eta_str}\n"
                f"📈Progress: {percent:.1f}%"
            )
            try:
                bot.edit_message_text(
                    text=text,
                    chat_id=chat_id,
                    message_id=status_message_id,
                    parse_mode="HTML",
                )
            except Exception:
                pass

        await client.send_file(
            entity=chat_id,
            file=file_path,
            caption=caption,
            force_document=True,
            progress_callback=progress_callback
            part_size_kb=2048,    # 2 MB chunks instead of 512 KB or 1 MB
            max_connections=16    # up to 16 parallel uploads
        )
    except Exception as e:
        logger.error(f"[Telethon] Failed to send {file_path} to chat {chat_id}: {e}", exc_info=True)
    finally:
        await client.disconnect()

def send_file_via_telethon_with_progress(chat_id: int, file_path: str, caption: str, status_message_id: int):
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
# 11) Background task for sending a single episode (download → upload → subtitle)
# ──────────────────────────────────────────────────────────────────────────────
def download_and_send_episode(chat_id: int, ep_num: str, episode_id: str):
    """
    1) Extract HLS link + subtitle URL
    2) Download HLS → MP4 into videos_cache/{chat_id}/Episode {ep_num}.mp4
    3) Upload via Telethon session telethon_bot_session_{chat_id}
    4) Download + send subtitle into subtitles_cache/{chat_id}/Episode {ep_num}.vtt
    Aborts immediately if cancel_events[chat_id].is_set().
    """
    cancel_event = cancel_events.get(chat_id)

    # If already cancelled, abort
    if cancel_event and cancel_event.is_set():
        return

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

    # ─── Ensure per-chat cache directories ───────────────────────────────────────────────
    video_cache_dir = os.path.join("videos_cache", str(chat_id))
    subtitle_cache_dir = os.path.join("subtitles_cache", str(chat_id))
    os.makedirs(video_cache_dir, exist_ok=True)
    os.makedirs(subtitle_cache_dir, exist_ok=True)

    # (b) Step 2: DOWNLOAD MP4 via ffmpeg
    status_download = bot.send_message(chat_id, "📥 Downloading File\nProgress: 0%")
    last_dl_update = [0.0]

    def download_progress_cb(downloaded_mb, total_duration_s, percent, speed_mb_s, elapsed_s, eta_s):
        if cancel_event and cancel_event.is_set():
            return

        now = time.time()
        if now - last_dl_update[0] < 3.0:
            return
        last_dl_update[0] = now

        elapsed_str = f"{int(elapsed_s//60)}m {int(elapsed_s%60)}s"
        eta_str = (
            f"{int(eta_s//60)}m {int(eta_s%60)}s"
            if (eta_s is not None and eta_s >= 0)
            else "–"
        )

        text = (
            "📥 <b>Downloading File</b>\n\n"
            f"📊Size: {downloaded_mb:.2f} MB\n"
            f"⚡️Speed: {speed_mb_s:.2f} MB/s\n"
            f"⏱️Time Elapsed: {elapsed_str}\n"
            f"⏳ETA: {eta_str}\n"
            f"📈Progress: {percent:.1f}%"
        )
        try:
            bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=status_download.message_id,
                parse_mode="HTML",
            )
        except Exception:
            pass

    try:
        raw_mp4 = download_and_rename_video(
            hls_link,
            ep_num,
            cache_dir=video_cache_dir,
            progress_callback=download_progress_cb
        )
    except Exception as e:
        logger.error(f"[Thread] Error downloading video (Episode {ep_num}): {e}", exc_info=True)
        try:
            bot.delete_message(chat_id=chat_id, message_id=status_download.message_id)
        except Exception:
            pass

        if cancel_event and cancel_event.is_set():
            bot.send_message(chat_id, f"❌ Download of Episode {ep_num} cancelled.")
            return

        # Fallback: send HLS link + subtitle
        bot.send_message(
            chat_id,
            f"⚠️ Failed to convert Episode {ep_num} to MP4. Here’s the HLS link instead:\n\n{hls_link}"
        )
        if subtitle_url:
            try:
                local_vtt = download_and_rename_subtitle(
                    subtitle_url, ep_num, cache_dir=subtitle_cache_dir
                )
                status_sub = bot.send_message(chat_id, f"✅ Subtitle downloaded as “Episode {ep_num}.vtt”.")
                bot.send_document(
                    chat_id=chat_id,
                    document=InputFile(open(local_vtt, "rb"), filename=f"Episode {ep_num}.vtt"),
                    caption=f"Here is the subtitle for Episode {ep_num}"
                )
                os.remove(local_vtt)
                try:
                    bot.delete_message(chat_id=chat_id, message_id=status_sub.message_id)
                except Exception:
                    pass
            except Exception as se:
                logger.error(f"[Thread] Error sending subtitle (Episode {ep_num}): {se}", exc_info=True)
                bot.send_message(chat_id, f"⚠️ Could not download/send subtitle for Episode {ep_num}.")
        return

    # Delete “Downloading File” status (download finished)
    try:
        bot.delete_message(chat_id=chat_id, message_id=status_download.message_id)
    except Exception:
        pass

    # If user cancelled after download, abort before upload
    if cancel_event and cancel_event.is_set():
        bot.send_message(chat_id, f"❌ Download of Episode {ep_num} was cancelled before upload.")
        try:
            os.remove(raw_mp4)
        except OSError:
            pass
        return

    # (c) Step 3: UPLOAD MP4 via Telethon
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
        try:
            bot.delete_message(chat_id=chat_id, message_id=status_upload.message_id)
        except Exception:
            pass

        if cancel_event and cancel_event.is_set():
            bot.send_message(chat_id, f"❌ Upload of Episode {ep_num} cancelled.")
            try:
                os.remove(raw_mp4)
            except OSError:
                pass
            return

        bot.send_message(chat_id, f"⚠️ Could not send Episode {ep_num} via Telethon. Here’s the HLS link:\n\n{hls_link}")
        try:
            os.remove(raw_mp4)
        except OSError:
            pass

        if subtitle_url:
            try:
                local_vtt = download_and_rename_subtitle(
                    subtitle_url, ep_num, cache_dir=subtitle_cache_dir
                )
                status_sub = bot.send_message(chat_id, f"✅ Subtitle downloaded as “Episode {ep_num}.vtt.”")
                bot.send_document(
                    chat_id=chat_id,
                    document=InputFile(open(local_vtt, "rb"), filename=f"Episode {ep_num}.vtt"),
                    caption=f"Here is the subtitle for Episode {ep_num}"
                )
                os.remove(local_vtt)
                try:
                    bot.delete_message(chat_id=chat_id, message_id=status_sub.message_id)
                except Exception:
                    pass
            except Exception as se:
                logger.error(f"[Thread] Error sending subtitle (Episode {ep_num}): {se}", exc_info=True)
                bot.send_message(chat_id, f"⚠️ Could not download/send subtitle for Episode {ep_num}.")
        return
    finally:
        # Clean up raw MP4 in any case
        try:
            os.remove(raw_mp4)
        except OSError:
            pass

    # Delete “Uploading File” status (upload finished)
    try:
        bot.delete_message(chat_id=chat_id, message_id=status_upload.message_id)
    except Exception:
        pass

    # (d) Step 4: Send subtitle via Bot API
    if not subtitle_url:
        bot.send_message(chat_id, "❗ No English subtitle (.vtt) found.")
        return

    if cancel_event and cancel_event.is_set():
        bot.send_message(chat_id, f"❌ Subtitle download for Episode {ep_num} cancelled.")
        return

    try:
        local_vtt = download_and_rename_subtitle(subtitle_url, ep_num, cache_dir=subtitle_cache_dir)
    except Exception as e:
        logger.error(f"[Thread] Error downloading subtitle (Episode {ep_num}): {e}", exc_info=True)
        bot.send_message(chat_id, f"⚠️ Found a subtitle URL but failed to download for Episode {ep_num}.")
        return

    status_sub = bot.send_message(chat_id, f"✅ Subtitle downloaded as “Episode {ep_num}.vtt.”")
    try:
        bot.send_document(
            chat_id=chat_id,
            document=InputFile(open(local_vtt, "rb"), filename=f"Episode {ep_num}.vtt"),
            caption=f"Here is the subtitle for Episode {ep_num}"
        )
    except Exception as e:
        logger.error(f"[Thread] Error sending subtitle (Episode {ep_num}): {e}", exc_info=True)
        bot.send_message(chat_id, f"⚠️ Could not send subtitle for Episode {ep_num}.")
    finally:
        try:
            os.remove(local_vtt)
        except OSError:
            pass

    try:
        bot.delete_message(chat_id=chat_id, message_id=status_sub.message_id)
    except Exception:
        pass

# ──────────────────────────────────────────────────────────────────────────────
# 12) Background task for “Download All” episodes (download→upload→subtitle)
# ──────────────────────────────────────────────────────────────────────────────
def download_and_send_all_episodes(chat_id: int, ep_list: list):
    """
    Download all episodes in ep_list sequentially, but abort if cancel_events[chat_id] is set.
    Each episode is handled in the same way as download_and_send_episode, using per-chat cache.
    """
    cancel_event = cancel_events.get(chat_id)

    from hianimez_scraper import extract_episode_stream_and_subtitle

    # Ensure per-chat cache directories exist
    video_cache_dir = os.path.join("videos_cache", str(chat_id))
    subtitle_cache_dir = os.path.join("subtitles_cache", str(chat_id))
    os.makedirs(video_cache_dir, exist_ok=True)
    os.makedirs(subtitle_cache_dir, exist_ok=True)

    for ep_num, episode_id in ep_list:
        # Check for cancellation
        if cancel_event and cancel_event.is_set():
            bot.send_message(chat_id, f"❌ Download‐All cancelled at Episode {ep_num}.")
            return

        try:
            hls_link, subtitle_url = extract_episode_stream_and_subtitle(episode_id)
        except Exception as e:
            logger.error(f"[Thread] Error extracting Episode {ep_num}: {e}", exc_info=True)
            bot.send_message(chat_id, f"❌ Failed to extract data for Episode {ep_num}. Skipping.")
            continue

        if not hls_link:
            bot.send_message(chat_id, f"😔 Episode {ep_num}: No SUB-HD2 stream found. Skipping.")
            continue

        # (b) Download raw MP4
        status_download = bot.send_message(chat_id, f"📥 Downloading Episode {ep_num}...\nProgress: 0%")
        last_dl_update = [0.0]

        def download_progress_cb(downloaded_mb, total_duration_s, percent, speed_mb_s, elapsed_s, eta_s):
            if cancel_event and cancel_event.is_set():
                return

            now = time.time()
            if now - last_dl_update[0] < 3.0:
                return
            last_dl_update[0] = now

            elapsed_str = f"{int(elapsed_s//60)}m {int(elapsed_s%60)}s"
            eta_str = (
                f"{int(eta_s//60)}m {int(eta_s%60)}s"
                if (eta_s is not None and eta_s >= 0)
                else "–"
            )
            text = (
                f"📥 <b>Downloading Episode {ep_num}</b>\n\n"
                f"📊Size: {downloaded_mb:.2f} MB\n"
                f"⚡️Speed: {speed_mb_s:.2f} MB/s\n"
                f"⏱️Time Elapsed: {elapsed_str}\n"
                f"⏳ETA: {eta_str}\n"
                f"📈Progress: {percent:.1f}%"
            )
            try:
                bot.edit_message_text(text, chat_id=chat_id, message_id=status_download.message_id, parse_mode="HTML")
            except Exception:
                pass

        try:
            raw_mp4 = download_and_rename_video(
                hls_link,
                ep_num,
                cache_dir=video_cache_dir,
                progress_callback=download_progress_cb
            )
        except Exception as e:
            logger.error(f"[Thread] Error downloading Episode {ep_num}: {e}", exc_info=True)
            try:
                bot.delete_message(chat_id=chat_id, message_id=status_download.message_id)
            except Exception:
                pass

            if cancel_event and cancel_event.is_set():
                bot.send_message(chat_id, f"❌ Download‐All cancelled during Episode {ep_num}.")
                return

            # Fallback: send HLS link + subtitles
            bot.send_message(
                chat_id,
                f"⚠️ Could not convert Episode {ep_num} to MP4. Here’s the HLS link:\n\n{hls_link}"
            )
            if subtitle_url:
                try:
                    local_vtt = download_and_rename_subtitle(
                        subtitle_url, ep_num, cache_dir=subtitle_cache_dir
                    )
                    status_sub = bot.send_message(chat_id, f"✅ Subtitle downloaded as “Episode {ep_num}.vtt.”")
                    bot.send_document(
                        chat_id=chat_id,
                        document=InputFile(open(local_vtt, "rb"), filename=f"Episode {ep_num}.vtt"),
                        caption=f"Here is the subtitle for Episode {ep_num}"
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

        # Delete “Downloading Episode…” status (download finished)
        try:
            bot.delete_message(chat_id=chat_id, message_id=status_download.message_id)
        except Exception:
            pass

        # If cancelled before upload, abort
        if cancel_event and cancel_event.is_set():
            bot.send_message(chat_id, f"❌ Download‐All cancelled before uploading Episode {ep_num}.")
            try:
                os.remove(raw_mp4)
            except OSError:
                pass
            return

        # (c) Upload via Telethon
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

            if cancel_event and cancel_event.is_set():
                bot.send_message(chat_id, f"❌ Download‐All cancelled during upload of Episode {ep_num}.")
                try:
                    os.remove(raw_mp4)
                except OSError:
                    pass
                return

            bot.send_message(chat_id, f"⚠️ Could not send Episode {ep_num} via Telethon. Here’s the HLS link:\n\n{hls_link}")
            try:
                os.remove(raw_mp4)
            except OSError:
                pass
            if subtitle_url:
                try:
                    local_vtt = download_and_rename_subtitle(
                        subtitle_url, ep_num, cache_dir=subtitle_cache_dir
                    )
                    status_sub = bot.send_message(chat_id, f"✅ Subtitle downloaded as “Episode {ep_num}.vtt.”")
                    bot.send_document(
                        chat_id=chat_id,
                        document=InputFile(open(local_vtt, "rb"), filename=f"Episode {ep_num}.vtt"),
                        caption=f"Here is the subtitle for Episode {ep_num}"
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

        # Delete “Uploading Episode…” status (upload finished)
        try:
            bot.delete_message(chat_id=chat_id, message_id=status_upload.message_id)
        except Exception:
            pass

        # (d) Send subtitle
        if not subtitle_url:
            bot.send_message(chat_id, f"❗ No English subtitle found for Episode {ep_num}.")
            continue

        if cancel_event and cancel_event.is_set():
            bot.send_message(chat_id, f"❌ Download‐All cancelled before subtitle of Episode {ep_num}.")
            return

        try:
            local_vtt = download_and_rename_subtitle(
                subtitle_url, ep_num, cache_dir=subtitle_cache_dir
            )
        except Exception as e:
            logger.error(f"[Thread] Error downloading subtitle (Episode {ep_num}): {e}", exc_info=True)
            bot.send_message(chat_id, f"⚠️ Could not download subtitle for Episode {ep_num}.")
            continue

        status_sub = bot.send_message(chat_id, f"✅ Subtitle downloaded as “Episode {ep_num}.vtt.”")
        try:
            bot.send_document(
                chat_id=chat_id,
                document=InputFile(open(local_vtt, "rb"), filename=f"Episode {ep_num}.vtt"),
                caption=f"Here is the subtitle for Episode {ep_num}"
            )
        except Exception as e:
            logger.error(f"[Thread] Error sending subtitle (Episode {ep_num}): {e}", exc_info=True)
            bot.send_message(chat_id, f"⚠️ Could not send subtitle for Episode {ep_num}.")
        finally:
            try:
                os.remove(local_vtt)
            except OSError:
                pass

        try:
            bot.delete_message(chat_id=chat_id, message_id=status_sub.message_id)
        except Exception:
            pass

# ──────────────────────────────────────────────────────────────────────────────
# 13) Error handler
# ──────────────────────────────────────────────────────────────────────────────
def error_handler(update: object, context: CallbackContext):
    logger.error("Exception while handling an update:", exc_info=context.error)
    if isinstance(update, Update) and update.callback_query:
        try:
            update.callback_query.message.reply_text("⚠️ Oops, something went wrong.")
        except Exception:
            pass

# ──────────────────────────────────────────────────────────────────────────────
# 14) Main: set up Updater + start polling
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    updater = Updater(token=BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    # Define a global `bot` so that helper threads can do bot.send_message(...)
    global bot
    bot = updater.bot

    # Register handlers
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("search", search_command))
    dp.add_handler(CommandHandler("cancel", cancel_command))
    dp.add_handler(CallbackQueryHandler(anime_callback, pattern=r"^anime_idx:"))
    dp.add_handler(CallbackQueryHandler(episode_callback, pattern=r"^episode_idx:"))
    dp.add_handler(CallbackQueryHandler(episodes_all_callback, pattern=r"^episode_all$"))
    dp.add_error_handler(error_handler)

    # Create top‐level cache dirs if they don’t exist
    os.makedirs("subtitles_cache", exist_ok=True)
    os.makedirs("videos_cache", exist_ok=True)

    updater.start_polling()
    logger.info("Bot started with long polling. Listening for updates…")
    updater.idle()
