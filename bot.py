import logging
import os
import re
from html import escape
from typing import Any

import httpx
from dotenv import load_dotenv
from telegram import (
    BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
)
from telegram.constants import ChatType, ParseMode
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes,
    MessageHandler, filters,
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
    "kn": "Kannada", "hi": "Hindi", "ta": "Tamil", "te": "Telugu",
    "ml": "Malayalam", "en": "English", "bn": "Bengali",
    "mr": "Marathi", "ur": "Urdu", "ja": "Japanese",
    "ko": "Korean", "zh": "Chinese", "es": "Spanish",
    "fr": "French", "de": "German",
}

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("dhanu-cinema-bot")


class MovieAPIError(Exception):
    pass


async def get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Provider request failed: %s", exc)
        raise MovieAPIError("The movie service is temporarily unavailable.") from exc
    if not isinstance(data, dict):
        raise MovieAPIError("The movie service returned an unexpected response.")
    return data


async def tmdb_get(path: str, **params: Any) -> dict[str, Any]:
    if not TMDB_API_KEY:
        raise MovieAPIError("TMDB_API_KEY is missing from Render environment variables.")
    params["api_key"] = TMDB_API_KEY
    return await get_json(f"{TMDB_BASE_URL}/{path.lstrip('/')}", params)


async def omdb_get(**params: Any) -> dict[str, Any] | None:
    if not OMDB_API_KEY:
        return None
    params["apikey"] = OMDB_API_KEY
    try:
        result = await get_json(OMDB_BASE_URL, params)
    except MovieAPIError:
        return None
    return result if result.get("Response") == "True" else None


def get_year(value: str | None) -> str:
    return value[:4] if value and len(value) >= 4 else "N/A"


def get_runtime_minutes(tmdb_runtime: Any, omdb_runtime: str | None = None) -> int | None:
    if isinstance(tmdb_runtime, int) and tmdb_runtime > 0:
        return tmdb_runtime
    if omdb_runtime and omdb_runtime != "N/A":
        match = re.search(r"(\d+)", omdb_runtime)
        if match:
            value = int(match.group(1))
            return value if value > 0 else None
    return None


def format_runtime(minutes: int | None) -> str:
    if not minutes:
        return "N/A"
    if minutes < 60:
        return f"{minutes} Minutes"
    hours, remaining = divmod(minutes, 60)
    return f"{minutes} Minutes ({hours} Hours {remaining} Minutes)"


def rating_5(value: Any) -> str:
    try:
        number = float(value)
        if number > 0:
            return f"{number / 2:.1f}"
    except (TypeError, ValueError):
        pass
    return "N/A"


def language_name(code: str | None) -> str:
    if not code:
        return "N/A"
    return LANGUAGE_NAMES.get(code, code.upper())


def movie_keyboard(movie_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎭 Cast & Crew", callback_data=f"cast:{movie_id}"),
            InlineKeyboardButton("🎞 Trailer", callback_data=f"trailer:{movie_id}"),
        ],
        [InlineKeyboardButton("✨ Similar Movies", callback_data=f"similar:{movie_id}")],
    ])


def tv_keyboard(tv_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎭 Cast & Crew", callback_data=f"casttv:{tv_id}"),
            InlineKeyboardButton("🎞 Trailer", callback_data=f"trailertv:{tv_id}"),
        ],
        [InlineKeyboardButton("✨ Similar Series", callback_data=f"similartv:{tv_id}")],
    ])


async def send_poster(message: Any, poster_path: str | None, caption: str,
                      keyboard: InlineKeyboardMarkup | None = None) -> None:
    if poster_path:
        await message.reply_photo(
            photo=f"{TMDB_IMAGE_BASE}{poster_path}",
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
    else:
        await message.reply_text(
            caption, parse_mode=ParseMode.HTML, reply_markup=keyboard,
            disable_web_page_preview=True,
        )


async def load_movie(movie_id: int) -> tuple[dict[str, Any], dict[str, Any] | None]:
    details = await tmdb_get(
        f"movie/{movie_id}", append_to_response="external_ids", language="en-US"
    )
    imdb_id = (details.get("external_ids") or {}).get("imdb_id")
    year = get_year(details.get("release_date"))
    omdb = await omdb_get(i=imdb_id, type="movie") if imdb_id else None
    if not omdb:
        omdb = await omdb_get(
            t=details.get("title") or details.get("original_title") or "",
            y=year if year != "N/A" else "", type="movie",
        )
    return details, omdb


def build_movie_message(details: dict[str, Any], omdb: dict[str, Any] | None) -> str:
    title = details.get("title") or details.get("original_title") or "Unknown"
    genres = ", ".join(x.get("name", "") for x in details.get("genres", []) if x.get("name"))
    genres = genres or (omdb.get("Genre") if omdb else None) or "N/A"
    year = get_year(details.get("release_date"))
    if year == "N/A" and omdb:
        year = get_year(omdb.get("Year"))
    language = (omdb.get("Language") if omdb and omdb.get("Language") != "N/A"
                else language_name(details.get("original_language")))
    runtime = get_runtime_minutes(details.get("runtime"), omdb.get("Runtime") if omdb else None)
    rating = rating_5(details.get("vote_average"))
    imdb_rating = omdb.get("imdbRating") if omdb else None
    imdb_line = f"\n⭐ ɪᴍᴅʙ - {escape(str(imdb_rating))}/10" if imdb_rating and imdb_rating != "N/A" else ""
    tagline = details.get("tagline")
    tagline_line = f"\n💬 <i>{escape(str(tagline))}</i>" if tagline else ""
    overview = details.get("overview")
    overview_line = f"\n\n📖 <b>STORY</b>\n{escape(str(overview)[:650])}" if overview else ""
    return (
        f"🎬 <b>{escape(str(title))}</b>{tagline_line}\n\n"
        f"🎭 ɢᴇɴʀᴇs - {escape(str(genres))}\n"
        f"📆 ʏᴇᴀʀ - {escape(str(year))}\n"
        f"〽️ ʀᴀᴛɪɴɢ - {escape(rating)} / 5" if rating != "N/A" else
        f"🎬 <b>{escape(str(title))}</b>{tagline_line}\n\n"
        f"🎭 ɢᴇɴʀᴇs - {escape(str(genres))}\n📆 ʏᴇᴀʀ - {escape(str(year))}\n〽️ ʀᴀᴛɪɴɢ - N/A"
    ) + (
        f"\n🔉 ʟᴀɴɢᴜᴀɢᴇ - {escape(str(language))}\n"
        f"🔂 ʀᴜɴ ᴛɪᴍᴇ - {escape(format_runtime(runtime))}"
        f"{imdb_line}{overview_line}\n\n<i>Data: TMDB"
        f"{' + OMDb' if omdb else ''}</i>"
    )


def build_tv_message(details: dict[str, Any]) -> str:
    title = details.get("name") or details.get("original_name") or "Unknown"
    genres = ", ".join(x.get("name", "") for x in details.get("genres", []) if x.get("name")) or "N/A"
    runtimes = details.get("episode_run_time") or []
    runtime = f"{runtimes[0]} min/episode" if runtimes else "N/A"
    networks = ", ".join(x.get("name", "") for x in details.get("networks", []) if x.get("name")) or "N/A"
    overview = details.get("overview")
    story = f"\n\n📖 <b>STORY</b>\n{escape(str(overview)[:650])}" if overview else ""
    return (
        f"📺 <b>{escape(str(title))}</b>\n\n"
        f"🎭 ɢᴇɴʀᴇs - {escape(genres)}\n"
        f"📆 ꜰɪʀsᴛ ᴀɪʀᴇᴅ - {escape(get_year(details.get('first_air_date')))}\n"
        f"〽️ ʀᴀᴛɪɴɢ - {escape(rating_5(details.get('vote_average')))} / 5\n"
        f"🔉 ʟᴀɴɢᴜᴀɢᴇ - {escape(language_name(details.get('original_language')))}\n"
        f"🔂 ᴇᴘɪsᴏᴅᴇ - {escape(runtime)}\n"
        f"📚 sᴇᴀsᴏɴs - {details.get('number_of_seasons', 'N/A')} | "
        f"Episodes - {details.get('number_of_episodes', 'N/A')}\n"
        f"📡 sᴛᴀᴛᴜs - {escape(str(details.get('status') or 'N/A'))}\n"
        f"🏢 ɴᴇᴛᴡᴏʀᴋ - {escape(networks)}{story}\n\n<i>Data: TMDB</i>"
    )


async def send_movie_result(message: Any, movie_id: int) -> None:
    try:
        details, omdb = await load_movie(movie_id)
        await send_poster(message, details.get("poster_path"),
                          build_movie_message(details, omdb), movie_keyboard(movie_id))
    except MovieAPIError as exc:
        await message.reply_text(f"⚠️ {escape(str(exc))}")
    except Exception:
        logger.exception("Movie details failed")
        await message.reply_text("⚠️ Could not load this title. Please try again.")


async def send_tv_result(message: Any, tv_id: int) -> None:
    try:
        details = await tmdb_get(f"tv/{tv_id}", language="en-US")
        await send_poster(message, details.get("poster_path"),
                          build_tv_message(details), tv_keyboard(tv_id))
    except MovieAPIError as exc:
        await message.reply_text(f"⚠️ {escape(str(exc))}")
    except Exception:
        logger.exception("TV details failed")
        await message.reply_text("⚠️ Could not load this series. Please try again.")


async def search_titles(message: Any, query: str, media_type: str = "movie") -> None:
    if not query or len(query) > 100:
        await message.reply_text("Send a title between 1 and 100 characters.")
        return
    waiting = await message.reply_text("🔎 Searching the TMDB database...")
    try:
        result = await tmdb_get(f"search/{media_type}", query=query,
                                include_adult="false", language="en-US", page=1)
        items = result.get("results") or []
        if not items:
            await waiting.edit_text(f"❌ No {media_type} results found for: {escape(query)}",
                                    parse_mode=ParseMode.HTML)
            return
        keyboard = []
        for item in items[:8]:
            item_id = item.get("id")
            if not item_id:
                continue
            title = item.get("title" if media_type == "movie" else "name") or "Untitled"
            date = item.get("release_date" if media_type == "movie" else "first_air_date")
            year = get_year(date)
            score = item.get("vote_average")
            label = f"{title[:35]} ({year})"
            if score:
                label += f" ⭐{float(score):.1f}"
            keyboard.append([InlineKeyboardButton(
                label[:60], callback_data=f"{media_type}:{item_id}"
            )])
        await waiting.edit_text(
            f"🎬 <b>Search results</b>\nQuery: <i>{escape(query)}</i>\n\nChoose a title:",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML,
        )
    except MovieAPIError as exc:
        await waiting.edit_text(f"⚠️ {escape(str(exc))}")
    except Exception:
        logger.exception("Title search failed")
        await waiting.edit_text("⚠️ Search failed. Please try again.")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or update.effective_chat.type != ChatType.PRIVATE:
        return
    await update.effective_message.reply_text(
        "🎬 <b>DHANU CINEMA</b>\n"
        "Your personal movie and series discovery assistant.\n\n"
        "🔎 Send any movie name to search.\n"
        "📺 Use /tv followed by a series name.\n"
        "🔥 Use /trending to discover popular movies.\n\n"
        "Explore posters, ratings, stories, cast, trailers and similar titles.\n"
        "🔒 Private chat only.",
        parse_mode=ParseMode.HTML,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or update.effective_chat.type != ChatType.PRIVATE:
        return
    await update.effective_message.reply_text(
        "<b>🎬 DHANU CINEMA — HOW TO USE</b>\n\n"
        "Send a movie title to search movies.\n"
        "Use /tv <code>series name</code> to search TV shows.\n"
        "Use /trending to see this week's trending movies.\n\n"
        "Select a result to view its poster, rating, genres, story and more.\n"
        "Then explore Cast & Crew, Trailer and Similar Titles buttons.\n\n"
        "<b>Commands</b>\n"
        "/start — Start the bot\n/help — Show help\n"
        "/trending — Trending movies\n/tv — Search TV series\n"
        "/credits — API credits",
        parse_mode=ParseMode.HTML,
    )


async def credits_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or update.effective_chat.type != ChatType.PRIVATE:
        return
    await update.effective_message.reply_text(
        "Movie and TV metadata and posters are provided by TMDB.\n"
        "This product uses the TMDB API but is not endorsed or certified by TMDB.\n\n"
        "Additional IMDb-related data may be provided by OMDb.\n"
        "TMDB: https://www.themoviedb.org\nOMDb: https://www.omdbapi.com/",
        disable_web_page_preview=True,
    )


async def tv_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or update.effective_chat.type != ChatType.PRIVATE:
        return
    query = " ".join(context.args).strip()
    if not query:
        await update.effective_message.reply_text("Usage: /tv <series name>")
        return
    await search_titles(update.effective_message, query, "tv")


async def trending_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or update.effective_chat.type != ChatType.PRIVATE:
        return
    waiting = await update.effective_message.reply_text("🔥 Loading this week's trending movies...")
    try:
        result = await tmdb_get("trending/movie/week", language="en-US")
        keyboard = []
        for item in (result.get("results") or [])[:10]:
            title = item.get("title") or "Untitled"
            year = get_year(item.get("release_date"))
            score = item.get("vote_average")
            label = f"{title[:36]} ({year})"
            if score:
                label += f" ⭐{float(score):.1f}"
            keyboard.append([InlineKeyboardButton(
                label[:60], callback_data=f"movie:{item['id']}"
            )])
        if keyboard:
            await waiting.edit_text("🔥 <b>TRENDING MOVIES THIS WEEK</b>\n\nChoose one:",
                                    reply_markup=InlineKeyboardMarkup(keyboard),
                                    parse_mode=ParseMode.HTML)
        else:
            await waiting.edit_text("No trending titles are available right now.")
    except MovieAPIError as exc:
        await waiting.edit_text(f"⚠️ {escape(str(exc))}")


async def search_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or update.effective_chat.type != ChatType.PRIVATE:
        return
    await search_titles(update.effective_message, (update.effective_message.text or "").strip())


async def show_cast(message: Any, media_type: str, media_id: int) -> None:
    credits = await tmdb_get(f"{media_type}/{media_id}/credits")
    cast = credits.get("cast") or []
    crew = credits.get("crew") or []
    directors = [x.get("name") for x in crew if x.get("job") in ("Director", "Executive Producer")]
    writers = [x.get("name") for x in crew if x.get("department") == "Writing"]
    lines = [f"🎭 <b>CAST & CREW</b>"]
    if directors:
        lines.append("🎬 Director: " + escape(", ".join(dict.fromkeys(directors[:3]))))
    if writers:
        lines.append("✍️ Writer: " + escape(", ".join(dict.fromkeys(writers[:3]))))
    if cast:
        lines.append("\n⭐ <b>MAIN CAST</b>")
        for person in cast[:12]:
            name = escape(str(person.get("name") or "Unknown"))
            role = escape(str(person.get("character") or ""))
            lines.append(f"• {name}" + (f" — {role}" if role else ""))
    else:
        lines.append("Cast information is not available.")
    await message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def show_trailer(message: Any, media_type: str, media_id: int) -> None:
    videos = await tmdb_get(f"{media_type}/{media_id}/videos")
    results = videos.get("results") or []
    candidates = [v for v in results if v.get("site") == "YouTube" and v.get("key")]
    candidates.sort(key=lambda v: (v.get("type") != "Trailer", v.get("official") is not True))
    if not candidates:
        await message.reply_text("🎞 No official trailer link was found in TMDB.")
        return
    video = candidates[0]
    url = f"https://www.youtube.com/watch?v={video['key']}"
    await message.reply_text(
        f"🎞 <b>{escape(str(video.get('name') or 'Official trailer'))}</b>\n"
        "Open the video on YouTube:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("▶️ Watch Trailer", url=url)]]),
    )


async def show_similar(message: Any, media_type: str, media_id: int) -> None:
    result = await tmdb_get(f"{media_type}/{media_id}/similar", language="en-US", page=1)
    items = result.get("results") or []
    keyboard = []
    for item in items[:8]:
        title = item.get("title" if media_type == "movie" else "name") or "Untitled"
        date = item.get("release_date" if media_type == "movie" else "first_air_date")
        keyboard.append([InlineKeyboardButton(
            f"{title[:42]} ({get_year(date)})"[:60],
            callback_data=f"{media_type}:{item['id']}",
        )])
    label = "MOVIES" if media_type == "movie" else "SERIES"
    await message.reply_text(
        f"✨ <b>SIMILAR {label}</b>\nChoose a title to explore:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
    )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    if not query.message or query.message.chat.type != ChatType.PRIVATE:
        await query.answer()
        return
    await query.answer()
    try:
        action, raw_id = (query.data or "").split(":", 1)
        media_id = int(raw_id)
        if action == "movie":
            await query.message.reply_text("⏳ Loading movie information...")
            await send_movie_result(query.message, media_id)
        elif action == "tv":
            await query.message.reply_text("⏳ Loading series information...")
            await send_tv_result(query.message, media_id)
        elif action in ("cast", "casttv"):
            await show_cast(query.message, "movie" if action == "cast" else "tv", media_id)
        elif action in ("trailer", "trailertv"):
            await show_trailer(query.message, "movie" if action == "trailer" else "tv", media_id)
        elif action in ("similar", "similartv"):
            await show_similar(query.message, "movie" if action == "similar" else "tv", media_id)
    except MovieAPIError as exc:
        await query.message.reply_text(f"⚠️ {escape(str(exc))}")
    except Exception:
        logger.exception("Button action failed")
        await query.message.reply_text("⚠️ This action failed. Please try again.")


async def post_init(application: Application) -> None:
    await application.bot.set_my_commands([
        BotCommand("start", "Start DHANU CINEMA"),
        BotCommand("help", "Show instructions"),
        BotCommand("trending", "Discover trending movies"),
        BotCommand("tv", "Search TV series"),
        BotCommand("credits", "View API credits"),
    ])


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Telegram update error: %s", context.error)


def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is missing from environment variables.")
    if not TMDB_API_KEY:
        raise SystemExit("TMDB_API_KEY is missing from environment variables.")

    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    private = filters.ChatType.PRIVATE
    application.add_handler(CommandHandler("start", start_command, filters=private))
    application.add_handler(CommandHandler("help", help_command, filters=private))
    application.add_handler(CommandHandler("credits", credits_command, filters=private))
    application.add_handler(CommandHandler("trending", trending_command, filters=private))
    application.add_handler(CommandHandler("tv", tv_command, filters=private))
    application.add_handler(CallbackQueryHandler(
        callback_handler,
        pattern=r"^(movie|tv|cast|casttv|trailer|trailertv|similar|similartv):\d+$",
    ))
    application.add_handler(MessageHandler(
        private & filters.TEXT & ~filters.COMMAND, search_message
    ))
    application.add_error_handler(error_handler)

    mode = os.getenv("TELEGRAM_MODE", "polling").strip().lower()
    if mode == "webhook":
        external_url = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
        webhook_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
        port = int(os.getenv("PORT", "10000"))
        if not external_url:
            raise SystemExit("RENDER_EXTERNAL_URL is missing; use a Render Web Service.")
        if not webhook_secret:
            raise SystemExit("TELEGRAM_WEBHOOK_SECRET is missing from Render environment variables.")
        logger.info("Starting DHANU CINEMA webhook on port %s.", port)
        application.run_webhook(
            listen="0.0.0.0", port=port, url_path="telegram-webhook",
            webhook_url=f"{external_url}/telegram-webhook",
            secret_token=webhook_secret, drop_pending_updates=True,
        )
    else:
        logger.info("DHANU CINEMA is running in polling mode.")
        application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
