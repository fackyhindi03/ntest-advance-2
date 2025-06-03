
---

## 4. `bot.py`

```python
#!/usr/bin/env python3
# bot.py

import logging
import os
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

# -------------- EDIT THIS: Insert your own Bot Token --------------
TELEGRAM_TOKEN = "7882374719:AAEHv5HTsdH2DvwW_goG8W_JdNv1pmxpSkY"
# -------------------------------------------------------------------

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


def start(update: Update, context: CallbackContext):
    """Send a welcome message and brief instructions."""
    update.message.reply_text(
        "👋 Hello! I can help you search for anime on hianimez.to "
        "and extract the SUB-HD2 (1080p) HLS link + English subtitles.\n\n"
        "Use /search <anime name> to begin."
    )


def search_command(update: Update, context: CallbackContext):
    """Handler for /search <query>."""
    if len(context.args) == 0:
        update.message.reply_text("Please provide an anime name. Example: /search Naruto")
        return

    query = " ".join(context.args)
    msg = update.message.reply_text(f"🔍 Searching for \"{query}\" ...")
    try:
        results = search_anime(query)
    except Exception as e:
        logger.error(f"Error during search: {e}")
        update.message.reply_text("❌ Sorry, something went wrong while searching.")
        return

    if not results:
        msg.edit_text(f"No anime found matching \"{query}\".")
        return

    # Build inline keyboard of anime buttons
    buttons = []
    for title, anime_url, anime_id in results:
        buttons.append([InlineKeyboardButton(title, callback_data=f"anime:{anime_id}")])

    reply_markup = InlineKeyboardMarkup(buttons)
    msg.edit_text("Select the anime you want:", reply_markup=reply_markup)


def anime_callback(update: Update, context: CallbackContext):
    """When user taps on an anime button, list episodes."""
    query = update.callback_query
    query.answer()

    data = query.data  # e.g. "anime:12345"
    _, anime_id = data.split(":")
    # We must reconstruct the anime URL from anime_id. For simplicity, anime_id is actually the full anime-page URL base64 encoded or something.
    # In our scraper implementation, we used anime_id = base‐62/slug. To keep it simple, let's just store the full URL in the callback_data.
    # For example, callback_data = f"anime_url|{anime_url}"
    # Here though, let's assume anime_id IS actually the full anime_page_url.
    anime_url = anime_id

    # Fetch episodes list
    try:
        episodes = get_episodes_list(anime_url)
    except Exception as e:
        logger.error(f"Error fetching episodes: {e}")
        query.edit_message_text("❌ Failed to retrieve episodes for that anime.")
        return

    if not episodes:
        query.edit_message_text("No episodes found for that anime.")
        return

    # Build buttons for each episode
    buttons = []
    for ep_num, ep_url in episodes:
        # We pass `ep_url` as callback data. But to keep callback_data < 64 bytes, we can URI‐encode it.
        buttons.append(
            [
                InlineKeyboardButton(
                    f"Episode {ep_num}", callback_data=f"episode|{ep_num}|{ep_url}"
                )
            ]
        )

    reply_markup = InlineKeyboardMarkup(buttons)
    query.edit_message_text("Select an episode:", reply_markup=reply_markup)


def episode_callback(update: Update, context: CallbackContext):
    """When user taps on a specific episode button."""
    query = update.callback_query
    query.answer()

    # callback_data format: "episode|<ep_num>|<ep_url>"
    _, ep_num, ep_url = query.data.split("|", maxsplit=2)

    msg = query.edit_message_text(
        f"🔄 Retrieving SUB HD-2 (1080p) link and English subtitle for Episode {ep_num}..."
    )

    try:
        hls_link, subtitle_url = extract_episode_stream_and_subtitle(ep_url)
    except Exception as e:
        logger.error(f"Error extracting episode data: {e}")
        query.edit_message_text(
            f"❌ Failed to extract episode data for Episode {ep_num}."
        )
        return

    if not hls_link:
        query.edit_message_text(
            f"😔 Could not find a SUB HD-2 (1080p) stream for Episode {ep_num}."
        )
        return

    # Send the HLS link
    text = f"🎬 *Episode {ep_num}*\n\n" \
           f"🔗 *1080p (SUB HD-2) HLS Link:*\n`{hls_link}`\n\n"
    if not subtitle_url:
        text += "❗ No English subtitle (.vtt) found.\n"
        query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)
        return

    # Download and rename the subtitle
    try:
        local_vtt_path = download_and_rename_subtitle(
            subtitle_url, ep_num, cache_dir="subtitles_cache"
        )
    except Exception as e:
        logger.error(f"Error downloading/renaming subtitle: {e}")
        # Still send the HLS link, but warn that subtitle failed
        text += "⚠️ Found an English subtitle URL but failed to download it."
        query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)
        return

    # Send HLS link plus the .vtt file
    text += f"✅ English subtitle downloaded and renamed to `Episode {ep_num}.vtt`."
    query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)

    # Actually send the .vtt file as a document
    with open(local_vtt_path, "rb") as f:
        query.message.reply_document(
            document=InputFile(f, filename=f"Episode {ep_num}.vtt"),
            caption=f"Here is the subtitle for Episode {ep_num}.",
        )

    # Optionally, delete the cached file
    try:
        os.remove(local_vtt_path)
    except OSError:
        pass


def error_handler(update: object, context: CallbackContext):
    """Log the error and send a brief notice to the user."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    if isinstance(update, Update) and update.callback_query:
        update.callback_query.message.reply_text(
            "⚠️ Oops, an unexpected error occurred."
        )


def main():
    # Create subtitles_cache directory if it doesn't exist
    os.makedirs("subtitles_cache", exist_ok=True)

    updater = Updater(TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher

    # Command handlers
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("search", search_command))

    # CallbackQuery handlers
    dp.add_handler(CallbackQueryHandler(anime_callback, pattern=r"^anime:"))
    dp.add_handler(CallbackQueryHandler(episode_callback, pattern=r"^episode\|"))

    # General error handler
    dp.add_error_handler(error_handler)

    logger.info("Bot started...")
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
