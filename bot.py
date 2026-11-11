import logging
import os
import re
from html import escape
from typing import Any

import httpx
from dotenv import load_dotenv
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType, ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "").strip()
OMDB_API_KEY = os.getenv("OMDB_API_KEY", "").strip()

TMDB_BASE_URL = "https://api.themoviedb.org/3"
OMDB_BASE_URL = "https://www.omdbapi.com/"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
HTTP_TIMEOUT = httpx.Timeout(20.0, connect=10.0)

LANGUAGE_NAMES = {
    "kn": "Kannada",
    "hi": "Hindi",
    "ta": "Tamil",
    "te": "Telugu",
    "ml": "Malayalam",
    "en": "English",
    "bn": "Bengali",
    "mr": "Marathi",
    "ur": "Urdu",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
}

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("tmdb-movie-info-bot")


class MovieAPIError(Exception):
    """Raised when a movie provider cannot return usable data."""


async def get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    """Request JSON from a provider and convert network/API failures to a clear error."""
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("API request failed: %s", exc)
        raise MovieAPIError("The movie service is temporarily unavailable.") from exc

    if not isinstance(data, dict):
        raise MovieAPIError("The movie service returned an unexpected response.")
    return data


async def tmdb_get(path: str, **params: Any) -> dict[str, Any]:
    if not TMDB_API_KEY:
        raise MovieAPIError("TMDB_API_KEY is missing from your .env file.")
    params["api_key"] = TMDB_API_KEY
    return await get_json(f"{TMDB_BASE_URL}/{path.lstrip('/')}", params)


async def omdb_get(**params: Any) -> dict[str, Any] | None:
    if not OMDB_API_KEY:
        return None

    params["apikey"] = OMDB_API_KEY
    try:
        result = await get_json(OMDB_BASE_URL, params)
    except MovieAPIError:
        logger.info("OMDb lookup failed; continuing with TMDB information.")
        return None

    if result.get("Response") != "True":
        return None
    return result


def get_year(value: str | None) -> str:
    return value[:4] if value and len(value) >= 4 else "N/A"


def get_runtime_minutes(tmdb_runtime: Any, omdb_runtime: str | None) -> int | None:
    if isinstance(tmdb_runtime, int) and tmdb_runtime > 0:
        return tmdb_runtime

    if omdb_runtime and omdb_runtime != "N/A":
        match = re.search(r"(\d+)", omdb_runtime)
        if match:
            minutes = int(match.group(1))
            return minutes if minutes > 0 else None
    return None


def format_runtime(minutes: int | None) -> str:
    if not minutes:
        return "N/A"

    if minutes < 60:
        return f"{minutes} Minutes"

    hours, remaining = divmod(minutes, 60)
    return f"{minutes} Minutes ({hours} Hours {remaining} Minutes)"


def format_rating(tmdb_rating: Any, omdb_rating: str | None) -> str:
    # TMDB uses a 10-point scale. Convert it to the requested 5-point format.
    try:
        value = float(tmdb_rating)
        if value > 0:
            return f"{value / 2:.1f} / 5"
    except (TypeError, ValueError):
        pass

    # OMDb's IMDb rating is also out of 10, so convert it to 5.
    try:
        if omdb_rating and omdb_rating != "N/A":
            return f"{float(omdb_rating) / 2:.1f} / 5"
    except (TypeError, ValueError):
        pass

    return "N/A"


def build_movie_message(details: dict[str, Any], omdb: dict[str, Any] | None) -> str:
    title = details.get("title") or details.get("original_title") or "Unknown"
    genre_list = details.get("genres") or []
    genres = ", ".join(
        item.get("name", "") for item in genre_list if item.get("name")
    )
    if not genres and omdb:
        genres = omdb.get("Genre", "N/A")
    genres = genres or "N/A"

    year = get_year(details.get("release_date"))
    if year == "N/A" and omdb:
        year = get_year(omdb.get("Year"))

    language = "N/A"
    if omdb and omdb.get("Language") and omdb["Language"] != "N/A":
        language = omdb["Language"]
    else:
        language_code = details.get("original_language", "")
        language = LANGUAGE_NAMES.get(language_code, language_code.upper() or "N/A")

    runtime = get_runtime_minutes(
        details.get("runtime"),
        omdb.get("Runtime") if omdb else None,
    )
    rating = format_rating(
        details.get("vote_average"),
        omdb.get("imdbRating") if omdb else None,
    )

    return (
        f"📝 ᴛɪᴛʟᴇ - {escape(str(title))}\n"
        f"🎭 ɢᴇɴʀᴇs - {escape(str(genres))}\n"
        f"📆 ʏᴇᴀʀ - {escape(str(year))}\n"
        f"〽️ ʀᴀᴛɪɴɢ - {escape(rating)}\n"
        f"🔉 ʟᴀɴɢᴜᴀɢᴇ - {escape(str(language))}\n"
        f"🔂 ʀᴜɴ ᴛɪᴍᴇ - {escape(format_runtime(runtime))}"
    )


async def load_movie(movie_id: int) -> tuple[dict[str, Any], dict[str, Any] | None]:
    details = await tmdb_get(
        f"movie/{movie_id}",
        append_to_response="external_ids",
        language="en-US",
    )

    external_ids = details.get("external_ids") or {}
    imdb_id = external_ids.get("imdb_id")
    release_year = get_year(details.get("release_date"))

    omdb = None
    if imdb_id:
        omdb = await omdb_get(i=imdb_id, type="movie")
    if not omdb:
        omdb = await omdb_get(
            t=details.get("title") or details.get("original_title") or "",
            y=release_year if release_year != "N/A" else "",
            type="movie",
        )

    return details, omdb


async def send_movie_result(chat_message: Any, movie_id: int) -> None:
    try:
        details, omdb = await load_movie(movie_id)
        caption = build_movie_message(details, omdb)
        poster_path = details.get("poster_path")

        if poster_path:
            poster_url = f"{TMDB_IMAGE_BASE}{poster_path}"
            await chat_message.reply_photo(
                photo=poster_url,
                caption=caption,
                parse_mode=ParseMode.HTML,
            )
        else:
            await chat_message.reply_text(
                caption,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
    except MovieAPIError as exc:
        await chat_message.reply_text(f"⚠️ {escape(str(exc))}")
    except Exception:
        logger.exception("Unexpected error while sending movie details")
        await chat_message.reply_text(
            "⚠️ Something went wrong while loading this movie. Please try again."
        )


async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not update.effective_chat or update.effective_chat.type != ChatType.PRIVATE:
        return

    await update.effective_message.reply_text(
        "🎬 <b>TMDB MOVIE INFO BOT</b>\n\n"
        "Send me a movie name and I’ll find its details in this format:\n"
        "Title • Genres • Year • Rating • Language • Runtime\n\n"
        "Use /help to see the commands.\n\n"
        "🔒 This bot works in private chat only.",
        parse_mode=ParseMode.HTML,
    )


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not update.effective_chat or update.effective_chat.type != ChatType.PRIVATE:
        return

    await update.effective_message.reply_text(
        "<b>How to use</b>\n"
        "1. Open this bot in a private chat.\n"
        "2. Send a movie title, for example: Anireekshita Atithigalu.\n"
        "3. Select the correct movie from the results.\n"
        "4. The bot sends the movie information and poster.\n\n"
        "<b>Commands</b>\n"
        "/start - Start the bot\n"
        "/help - Show instructions\n"
        "/credits - View API credits",
        parse_mode=ParseMode.HTML,
    )


async def credits_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not update.effective_chat or update.effective_chat.type != ChatType.PRIVATE:
        return

    await update.effective_message.reply_text(
        "Movie metadata and posters are provided by TMDB.\n"
        "This product uses the TMDB API but is not endorsed or certified by TMDB.\n\n"
        "Additional IMDb-related data may be provided by OMDb.\n"
        "TMDB: https://www.themoviedb.org\n"
        "OMDb: https://www.omdbapi.com/",
        disable_web_page_preview=True,
    )


async def search_movies(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not update.effective_chat or update.effective_chat.type != ChatType.PRIVATE:
        return

    query = (update.effective_message.text or "").strip()
    if not query:
        return
    if len(query) > 100:
        await update.effective_message.reply_text(
            "Please send a shorter movie title (maximum 100 characters)."
        )
        return

    waiting_message = await update.effective_message.reply_text("🔎 Searching movies...")
    try:
        result = await tmdb_get(
            "search/movie",
            query=query,
            include_adult="false",
            language="en-US",
            page=1,
        )
        movies = result.get("results") or []

        if not movies:
            await waiting_message.edit_text(
                f"❌ No movie found for: {escape(query)}",
                parse_mode=ParseMode.HTML,
            )
            return

        keyboard = []
        for movie in movies[:6]:
            movie_id = movie.get("id")
            if not movie_id:
                continue
            title = movie.get("title") or movie.get("original_title") or "Untitled"
            year = get_year(movie.get("release_date"))
            button_label = f"{title[:42]} ({year})"
            keyboard.append(
                [InlineKeyboardButton(button_label[:60], callback_data=f"movie:{movie_id}")]
            )

        if not keyboard:
            await waiting_message.edit_text("❌ No usable movie result was found.")
            return

        await waiting_message.edit_text(
            f"🎬 Results for <b>{escape(query)}</b>\n\nSelect the correct movie:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML,
        )
    except MovieAPIError as exc:
        await waiting_message.edit_text(f"⚠️ {escape(str(exc))}")
    except Exception:
        logger.exception("Movie search failed")
        await waiting_message.edit_text(
            "⚠️ Search failed unexpectedly. Please try again."
        )


async def movie_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query
    if not query:
        return
    if not query.message or query.message.chat.type != ChatType.PRIVATE:
        await query.answer()
        return

    await query.answer("Loading movie information...")
    try:
        movie_id = int((query.data or "").split(":", 1)[1])
    except (IndexError, ValueError):
        await query.message.edit_text("⚠️ Invalid movie selection. Search again.")
        return

    await query.message.edit_text("✅ Movie selected. Loading details...")
    await send_movie_result(query.message, movie_id)


async def post_init(application: Application) -> None:
    await application.bot.set_my_commands(
        [
            BotCommand("start", "Start the movie information bot"),
            BotCommand("help", "Show usage instructions"),
            BotCommand("credits", "View API credits"),
        ]
    )


async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    logger.error("Telegram update error: %s", context.error)


def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is missing. Add it to your .env file.")
    if not TMDB_API_KEY:
        raise SystemExit("TMDB_API_KEY is missing. Add it to your .env file.")

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    private_chats = filters.ChatType.PRIVATE
    application.add_handler(CommandHandler("start", start_command, filters=private_chats))
    application.add_handler(CommandHandler("help", help_command, filters=private_chats))
    application.add_handler(CommandHandler("credits", credits_command, filters=private_chats))
    application.add_handler(CallbackQueryHandler(movie_callback, pattern=r"^movie:\d+$"))
    application.add_handler(
        MessageHandler(
            private_chats & filters.TEXT & ~filters.COMMAND,
            search_movies,
        )
    )
    application.add_error_handler(error_handler)

    mode = os.getenv("TELEGRAM_MODE", "polling").strip().lower()
    if mode == "webhook":
        # Render Web Service deployment: Telegram sends updates to this public HTTPS endpoint.
        external_url = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
        webhook_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
        port = int(os.getenv("PORT", "10000"))
        webhook_path = "telegram-webhook"

        if not external_url:
            raise SystemExit("RENDER_EXTERNAL_URL is missing; configure this as a Render Web Service.")
        if not webhook_secret:
            raise SystemExit("TELEGRAM_WEBHOOK_SECRET is missing; set it in Render environment variables.")

        logger.info("Starting Telegram webhook on port %s (private chats only).", port)
        application.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=webhook_path,
            webhook_url=f"{external_url}/{webhook_path}",
            secret_token=webhook_secret,
            drop_pending_updates=True,
        )
    else:
        logger.info("TMDB Movie Info Bot is running in polling mode (private chats only).")
        application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
