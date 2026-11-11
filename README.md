# TMDB Movie Info Bot

A private-chat-only Telegram bot that searches movies and returns clean, compact information in the requested format.

Example reply:

📝 ᴛɪᴛʟᴇ - Anireekshita Atithigalu
🎭 ɢᴇɴʀᴇs - Crime, Thriller, Drama
📆 ʏᴇᴀʀ - 2026
〽️ ʀᴀᴛɪɴɢ - 2.0 / 5
🔉 ʟᴀɴɢᴜᴀɢᴇ - Kannada
🔂 ʀᴜɴ ᴛɪᴍᴇ - 161 Minutes (2 Hours 41 Minutes)

## Features

- Private-chat-only: group messages are ignored.
- Search movies by title.
- Select the correct result when several movies have similar names.
- Shows a movie poster when TMDB provides one.
- Displays title, genres, release year, rating, language, and runtime.
- Uses TMDB for movie metadata and OMDb for optional IMDb-related data.
- Converts 10-point provider ratings to the requested 5-point display.
- Keeps API keys in a local .env file that is excluded from Git.

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

## API behaviour

- TMDB supplies movie search results, genres, release date, runtime, original language, rating, and poster.
- OMDb is optional and supplies additional IMDb-related metadata and fallback values.
- The displayed rating is converted to a 5-point scale. For example, a provider rating of 4.0/10 is displayed as 2.0/5.
- If OMDb is not configured or does not find a match, the bot continues using TMDB data.

## Commands

- /start - Start the bot
- /help - Show instructions
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
