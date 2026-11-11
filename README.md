# DHANU CINEMA — Telegram Movie & Series Bot

A private-chat-only Telegram bot that searches movies and returns clean, compact information in the requested format.

Example reply:

📝 ᴛɪᴛʟᴇ - Anireekshita Atithigalu
🎭 ɢᴇɴʀᴇs - Crime, Thriller, Drama
📆 ʏᴇᴀʀ - 2026
〽️ ʀᴀᴛɪɴɢ - 2.0 / 5
🔉 ʟᴀɴɢᴜᴀɢᴇ - Kannada
🔂 ʀᴜɴ ᴛɪᴍᴇ - 161 Minutes (2 Hours 41 Minutes)

## Features

- Search movies by title and select from interactive results.
- Search TV series with /tv.
- Discover this week's trending movies with /trending.
- Movie and series posters, ratings, genres, release information, and story summaries.
- Interactive Cast & Crew, Trailer, and Similar Titles buttons.
- Optional IMDb rating data through OMDb.
- Converts 10-point provider ratings to a 5-point display.
- Private-chat-only operation; group messages are ignored.
- Keeps API keys in environment variables or a local .env file excluded from Git.

## Requirements

- Python 3.10 or newer.
- A Telegram bot token from https://t.me/BotFather.
- A TMDB API key from https://www.themoviedb.org/settings/api.
- An OMDb API key from https://www.omdbapi.com/ (optional).

## Run on Termux (Android)

Important: keep this project under Termux's home directory ($HOME). Do not create the virtual environment inside /storage/emulated/0/Download; Android shared storage does not support all filesystem operations required by Python virtual environments.

Install the tools:

    pkg update && pkg upgrade -y
    pkg install python git nano -y

Clone the repository into Termux home:

    cd ~
    git clone https://github.com/dhanush893/Tmdb.git
    cd Tmdb

Create and activate the virtual environment:

    python -m venv .venv
    source .venv/bin/activate

Install the dependencies:

    python -m pip install -r requirements.txt

Create your private environment file:

    cp .env.example .env
    nano .env

Add your own values to .env:

    TELEGRAM_BOT_TOKEN=your_bot_token
    TMDB_API_KEY=your_tmdb_api_key
    OMDB_API_KEY=your_omdb_api_key

Save the file, then start the bot:

    python bot.py

Open your bot in Telegram, press Start, and send a movie title.


## Deploy on Render

This repository is configured for a Render **Web Service** using Telegram webhooks. This avoids needing a paid background worker.

1. Push the repository to GitHub (the Render blueprint file is `render.yaml`).
2. Open https://render.com/ and sign in with GitHub.
3. Choose **New +** → **Blueprint** and select `dhanush893/Tmdb`.
4. Review the service named `tmdb-movie-info-bot` and deploy it.
5. In the service's **Environment** settings, add these secret values:
   - `TELEGRAM_BOT_TOKEN` — token from @BotFather.
   - `TMDB_API_KEY` — your TMDB API key.
   - `TELEGRAM_WEBHOOK_SECRET` — a random 32+ character string using only letters, numbers, underscores, and hyphens.
   - `OMDB_API_KEY` — optional.
6. Save changes and let Render redeploy. Check **Logs** for the startup message.
7. Open the Telegram bot privately and send a movie title.

Render sets `RENDER_EXTERNAL_URL` and `PORT` for the Web Service. The app uses these to register the Telegram webhook. Do not set `TELEGRAM_MODE` to polling on Render.

Generate a webhook secret locally in Termux without sharing it:

    python -c "import secrets; print(secrets.token_urlsafe(32))"

Paste the generated value directly into Render's Environment settings. Never put real tokens or secrets in GitHub.

**Free-plan note:** Render free web services can spin down after inactivity. The first Telegram message after a spin-down may take longer while the service wakes up. Check Render's current plan limits before deploying.

## API behaviour

- TMDB supplies movie search results, genres, release date, runtime, original language, rating, and poster.
- OMDb is optional and supplies additional IMDb-related metadata and fallback values.
- TV series, weekly trending titles, cast/crew, trailers, and similar-title lists are retrieved from TMDB.
- The displayed rating is converted to a 5-point scale. For example, a provider rating of 4.0/10 is displayed as 2.0/5.
- If OMDb is not configured or does not find a match, the bot continues using TMDB data.

## Commands

- /start - Start the bot
- /help - Show instructions
- /trending - Discover this week's trending movies
- /tv <series name> - Search TV series
- /credits - Show API credits

## Security

- Never commit your real .env file.
- Never paste bot tokens or API keys into public issues, screenshots, or chat messages.
- If a token is exposed, revoke or rotate it with the relevant provider.
- The repository includes .env.example only; it contains no working credentials.

## Credits and attribution

Movie metadata and posters are provided by TMDB. This product uses the TMDB API but is not endorsed or certified by TMDB. Review TMDB's current FAQ and attribution requirements at https://developer.themoviedb.org/docs/faq and use an approved TMDB logo from https://www.themoviedb.org/about/logos-attribution to identify API use in the bot's credits.

Additional IMDb-related data may be provided by OMDb: https://www.omdbapi.com/.

## Start command

    python bot.py
