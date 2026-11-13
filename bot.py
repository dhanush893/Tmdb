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
TMDB_BACKDROP_BASE = "https://image.tmdb.org/t/p/w780"
HTTP_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
WATERMARK = '⚜️ <b>ᴘᴏᴡᴇʀᴇᴅ ʙʏ:</b> <a href="https://t.me/SD_Movie_Adda">@SD_Movie_Adda</a>'

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
                      keyboard: InlineKeyboardMarkup | None = None,
                      artwork: str = "backdrop") -> None:
    if poster_path:
        image_base = TMDB_BACKDROP_BASE if artwork == "backdrop" else TMDB_IMAGE_BASE
        await message.reply_photo(
            photo=f"{image_base}{poster_path}",
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
    imdb_rating = omdb.get("imdbRating") if omdb else None
    tmdb_rating = details.get("vote_average")
    if imdb_rating and imdb_rating != "N/A":
        rating_line = f"〽️ ʀᴀᴛɪɴɢ - {escape(str(imdb_rating))} / 10 (IMDb)"
    elif tmdb_rating:
        rating_line = f"〽️ ʀᴀᴛɪɴɢ - {escape(str(round(float(tmdb_rating), 1)))} / 10 (TMDB)"
    else:
        rating_line = "〽️ ʀᴀᴛɪɴɢ - N/A"
    tagline = details.get("tagline")
    tagline_line = f"\\n💬 {escape(str(tagline))}" if tagline else ""
    return (
        f"🎬 <b>{escape(str(title))}</b>{tagline_line}\\n\\n"
        f"🎭 ɢᴇɴʀᴇs - {escape(str(genres))}\\n"
        f"📆 ʏᴇᴀʀ - {escape(str(year))}\\n"
        f"{rating_line}\\n"
        f"🔉 ʟᴀɴɢᴜᴀɢᴇ - {escape(str(language))}\\n"
        f"🔂 ʀᴜɴ ᴛɪᴍᴇ - {escape(format_runtime(runtime))}\\n\\n"
        f"{WATERMARK}"
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
        f"🏢 ɴᴇᴛᴡᴏʀᴋ - {escape(networks)}{story}\n\n{WATERMARK}"
    )


async def send_movie_result(message: Any, movie_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        details, omdb = await load_movie(movie_id)
        artwork = context.user_data.get("settings", {}).get("artwork", "backdrop")
        image_path = details.get("backdrop_path") if artwork == "backdrop" else details.get("poster_path")
        if not image_path:
            image_path = details.get("poster_path") or details.get("backdrop_path")
        actual_artwork = "backdrop" if image_path == details.get("backdrop_path") else "poster"
        caption = build_movie_message(details, omdb)
        if image_path:
            image_base = TMDB_BACKDROP_BASE if actual_artwork == "backdrop" else TMDB_IMAGE_BASE
            await message.reply_photo(
                photo=f"{image_base}{image_path}",
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=movie_keyboard(movie_id),
            )
        else:
            await message.reply_text(
                caption, parse_mode=ParseMode.HTML, reply_markup=movie_keyboard(movie_id),
                disable_web_page_preview=True,
            )
    except MovieAPIError as exc:
        await message.reply_text(f"⚠️ {escape(str(exc))}")
    except Exception:
        logger.exception("Movie details failed")
        await message.reply_text("⚠️ Could not load this title. Please try again.")


async def send_tv_result(message: Any, tv_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        details = await tmdb_get(f"tv/{tv_id}", language="en-US")
        artwork = context.user_data.get("settings", {}).get("artwork", "backdrop")
        image_path = details.get("backdrop_path") if artwork == "backdrop" else details.get("poster_path")
        if not image_path:
            image_path = details.get("poster_path") or details.get("backdrop_path")
        actual_artwork = "backdrop" if image_path == details.get("backdrop_path") else "poster"
        caption = build_tv_message(details)
        if image_path:
            image_base = TMDB_BACKDROP_BASE if actual_artwork == "backdrop" else TMDB_IMAGE_BASE
            await message.reply_photo(
                photo=f"{image_base}{image_path}",
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=tv_keyboard(tv_id),
            )
        else:
            await message.reply_text(
                caption, parse_mode=ParseMode.HTML, reply_markup=tv_keyboard(tv_id),
                disable_web_page_preview=True,
            )
    except MovieAPIError as exc:
        await message.reply_text(f"⚠️ {escape(str(exc))}")
    except Exception:
        logger.exception("TV details failed")
        await message.reply_text("⚠️ Could not load this series. Please try again.")


async def search_titles(message: Any, query: str, media_type: str = "movie", context: ContextTypes.DEFAULT_TYPE | None = None) -> None:
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
        result_limit = int(context.user_data.get("settings", {}).get("results", 8)) if context else 8
        for item in items[:result_limit]:
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


def settings_keyboard(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    settings = context.user_data.setdefault("settings", {})
    artwork = settings.get("artwork", "backdrop")
    count = int(settings.get("results", 8))
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(("✅ " if artwork == "backdrop" else "") + "🎞 Cinematic backdrop", callback_data="setting:artwork:backdrop")],
        [InlineKeyboardButton(("✅ " if artwork == "poster" else "") + "🖼 Original poster", callback_data="setting:artwork:poster")],
        [
            InlineKeyboardButton(("✅ " if count == 5 else "") + "5 results", callback_data="setting:results:5"),
            InlineKeyboardButton(("✅ " if count == 8 else "") + "8 results", callback_data="setting:results:8"),
            InlineKeyboardButton(("✅ " if count == 10 else "") + "10 results", callback_data="setting:results:10"),
        ],
    ])


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or update.effective_chat.type != ChatType.PRIVATE:
        return
    settings = context.user_data.setdefault("settings", {})
    settings.setdefault("artwork", "backdrop")
    settings.setdefault("results", 8)
    await update.effective_message.reply_text(
        "⚙️ <b>DHANU CINEMA SETTINGS</b>\n\n"
        "Choose your preferred artwork and search display.\n"
        "🎞 Cinematic backdrop: wide landscape image like your example.\n"
        "🖼 Original poster: vertical movie poster.\n"
        "🔢 Choose how many search results to show.",
        parse_mode=ParseMode.HTML, reply_markup=settings_keyboard(context),
    )


async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message or query.message.chat.type != ChatType.PRIVATE:
        if query:
            await query.answer()
        return
    parts = (query.data or "").split(":")
    if len(parts) != 3:
        await query.answer()
        return
    _, key, value = parts
    settings = context.user_data.setdefault("settings", {})
    if key == "artwork" and value in ("backdrop", "poster"):
        settings["artwork"] = value
        label = "Cinematic backdrop" if value == "backdrop" else "Original poster"
    elif key == "results" and value in ("5", "8", "10"):
        settings["results"] = int(value)
        label = value + " search results"
    else:
        await query.answer("Unknown setting.")
        return
    await query.answer("Updated: " + label)
    await query.edit_message_reply_markup(reply_markup=settings_keyboard(context))

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
        "/settings — Customize bot settings\n/credits — API credits",
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
    await search_titles(update.effective_message, query, "tv", context)


async def trending_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or update.effective_chat.type != ChatType.PRIVATE:
        return
    waiting = await update.effective_message.reply_text("🔥 Loading this week's trending movies...")
    try:
        result = await tmdb_get("trending/movie/week", language="en-US")
        keyboard = []
        for item in (result.get("results") or [])[:int(context.user_data.get("settings", {}).get("results", 8))]:
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
    await search_titles(update.effective_message, (update.effective_message.text or "").strip(), context=context)


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
            await send_movie_result(query.message, media_id, context)
        elif action == "tv":
            await query.message.reply_text("⏳ Loading series information...")
            await send_tv_result(query.message, media_id, context)
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
        BotCommand("settings", "Customize artwork and results"),
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
    application.add_handler(CommandHandler("settings", settings_command, filters=private))
    application.add_handler(CallbackQueryHandler(settings_callback, pattern=r"^setting:(artwork|results):(backdrop|poster|5|8|10)$"))
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
