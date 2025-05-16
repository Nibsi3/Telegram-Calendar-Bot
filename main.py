#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import logging
import json
import html
import random
import traceback
import aiohttp
from datetime import datetime, timedelta, timezone

# Load environment variables from .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # If python-dotenv is not installed, skip loading .env

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters, JobQueue

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ====== Configuration ======
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TMDB_API_KEY = os.getenv("TMDB_API_KEY")
OMDB_API_KEY = os.getenv("OMDB_API_KEY")
TVMAZE_API_KEY = os.getenv("TVMAZE_API_KEY")

if not TELEGRAM_TOKEN or not TMDB_API_KEY:
    raise EnvironmentError("Please set the TELEGRAM_TOKEN and TMDB_API_KEY environment variables.")

SCOPES = ['https://www.googleapis.com/auth/calendar.events']

# ====== Logging Setup ======
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

print('main.py starting...', file=sys.stderr)
try:
    # ====== Helper Functions ======
    def get_utc_today():
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).date()

    async def fetch_json(session: aiohttp.ClientSession, url: str, params: dict):
        """Fetch JSON data asynchronously from a URL with parameters."""
        async with session.get(url, params=params) as response:
            response.raise_for_status()
            return await response.json()

    async def search_tmdb(query: str = None, media_type: str = "movie", max_results: int = 50):
        """
        Search TMDB API for movies or TV series.
        If query is None, fetch upcoming titles airing in the next 30 days (across multiple pages).
        """
        base_url = "https://api.themoviedb.org/3"
        results = []
        max_pages = 5  # Avoid excessive API calls
        async with aiohttp.ClientSession() as session:
            if query:
                url = f"{base_url}/search/{media_type}"
                params = {"api_key": TMDB_API_KEY, "query": query, "language": "en-US", "page": 1}
                data = await fetch_json(session, url, params)
                results = data.get("results", [])[:max_results]
            else:
                now = get_utc_today()
                cutoff = now + timedelta(days=30)
                if media_type == "tv":
                    url = f"{base_url}/discover/tv"
                    params = {
                        "api_key": TMDB_API_KEY,
                        "language": "en-US",
                        "sort_by": "popularity.desc",  # Sort by popularity, not air date
                        "first_air_date.gte": now.isoformat(),
                        "first_air_date.lte": cutoff.isoformat(),
                        "page": 1
                    }
                    data = await fetch_json(session, url, params)
                    results = data.get("results", [])[:max_results]
                else:
                    page = 1
                    while len(results) < max_results and page <= max_pages:
                        url = f"{base_url}/movie/upcoming"
                        params = {"api_key": TMDB_API_KEY, "language": "en-US", "page": page}
                        data = await fetch_json(session, url, params)
                        page_results = data.get("results", [])
                        for item in page_results:
                            date_str = item.get("release_date")
                            if date_str:
                                try:
                                    date = datetime.strptime(date_str, "%Y-%m-%d").date()
                                    if now <= date <= cutoff:
                                        results.append(item)
                                        if len(results) >= max_results:
                                            break
                                except Exception:
                                    continue
                        if not data.get("results") or len(page_results) == 0:
                            break  # No more pages
                        page += 1
        return results[:max_results]

    def get_calendar_service():
        """Authenticate and return Google Calendar API service instance."""
        creds = None
        token_path = "token.json"
        creds_path = "credentials.json"

        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(creds_path):
                    raise FileNotFoundError("Missing credentials.json file for Google OAuth.")
                flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
                creds = flow.run_local_server(port=0)

            with open(token_path, "w", encoding="utf-8") as token_file:
                token_file.write(creds.to_json())

        return build('calendar', 'v3', credentials=creds)

    async def search_omdb(title: str, media_type: str = None):
        """Search OMDb API for a movie or series by title."""
        if not OMDB_API_KEY:
            raise EnvironmentError("Please set the OMDB_API_KEY environment variable.")
        base_url = "https://www.omdbapi.com/"
        params = {"apikey": OMDB_API_KEY, "t": title}
        if media_type:
            params["type"] = media_type
        async with aiohttp.ClientSession() as session:
            async with session.get(base_url, params=params) as response:
                response.raise_for_status()
                return await response.json()

    # TVMAZE_API_KEY for future use if needed
    if TVMAZE_API_KEY is None:
        print("Warning: TVMAZE_API_KEY environment variable is not set. TVmaze API features may not work.")

    async def fetch_tvmaze_upcoming_shows(max_results=10):
        """Fetch upcoming TV shows (including new seasons) from TVmaze schedule API."""
        import aiohttp
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc).date()
        url = f"https://api.tvmaze.com/schedule"
        shows = []
        async with aiohttp.ClientSession() as session:
            for i in range(0, 30):
                day = now + timedelta(days=i)
                params = {"country": "US", "date": day.isoformat()}
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    for entry in data:
                        show = entry.get("show", {})
                        if not show:
                            continue
                        # Only add if not already in list (by TVmaze id and season)
                        unique_key = f"{show.get('id')}_s{entry.get('season')}_e{entry.get('number')}"
                        if unique_key not in [s.get('unique_key') for s in shows]:
                            show_copy = show.copy()
                            show_copy["_episode_name"] = entry.get("name")
                            show_copy["_airdate"] = entry.get("airdate")
                            show_copy["_season"] = entry.get("season")
                            show_copy["_episode"] = entry.get("number")
                            show_copy["unique_key"] = unique_key
                            shows.append(show_copy)
                        if len(shows) >= max_results:
                            break
                if len(shows) >= max_results:
                    break
        return shows[:max_results]

    async def fetch_trending_tv_shows(max_results=10):
        """Fetch trending TV shows (weekly) from TMDB."""
        base_url = "https://api.themoviedb.org/3/trending/tv/week"
        async with aiohttp.ClientSession() as session:
            params = {"api_key": TMDB_API_KEY, "language": "en-US", "page": 1}
            data = await fetch_json(session, base_url, params)
            return data.get("results", [])[:max_results]

    async def fetch_upcoming_tv_shows(max_results=10):
        """Fetch upcoming TV shows (new shows) from TMDB."""
        base_url = "https://api.themoviedb.org/3/discover/tv"
        now = get_utc_today()
        async with aiohttp.ClientSession() as session:
            params = {
                "api_key": TMDB_API_KEY,
                "language": "en-US",
                "sort_by": "first_air_date.asc",
                "first_air_date.gte": now.isoformat(),
                "with_original_language": "en",
                "page": 1
            }
            data = await fetch_json(session, base_url, params)
            return data.get("results", [])[:max_results]

    async def fetch_new_seasons_of_popular_shows(max_results=10):
        """Fetch popular TV shows and return those with a new season airing in the future."""
        base_url = "https://api.themoviedb.org/3/tv/popular"
        now = get_utc_today()
        results = []
        async with aiohttp.ClientSession() as session:
            params = {"api_key": TMDB_API_KEY, "language": "en-US", "page": 1}
            data = await fetch_json(session, base_url, params)
            for show in data.get("results", []):
                tv_id = show.get("id")
                details_url = f"https://api.themoviedb.org/3/tv/{tv_id}"
                details_params = {"api_key": TMDB_API_KEY, "language": "en-US"}
                details = await fetch_json(session, details_url, details_params)
                for season in details.get("seasons", []):
                    air_date = season.get("air_date")
                    if air_date:
                        try:
                            air_date_obj = datetime.strptime(air_date, "%Y-%m-%d").date()
                            if air_date_obj >= now:
                                show_copy = show.copy()
                                show_copy["_season_number"] = season.get("season_number")
                                show_copy["_season_air_date"] = air_date
                                results.append(show_copy)
                                break
                        except Exception:
                            continue
                if len(results) >= max_results:
                    break
        return results[:max_results]

    async def fetch_on_the_air_tv_shows(max_results=10):
        """Fetch TV shows currently on the air from TMDB."""
        base_url = "https://api.themoviedb.org/3/tv/on_the_air"
        async with aiohttp.ClientSession() as session:
            params = {"api_key": TMDB_API_KEY, "language": "en-US", "page": 1}
            data = await fetch_json(session, base_url, params)
            return data.get("results", [])[:max_results]

    async def fetch_tvmaze_new_and_returning_shows(days=30, max_results=20):
        """Fetch new series and new season premieres from TVmaze schedule API for the next N days."""
        import aiohttp
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc).date()
        exclude_genres = {"soap", "news", "talk", "reality", "game show", "documentary"}
        seen = set()
        shows = []
        async with aiohttp.ClientSession() as session:
            for i in range(days):
                day = now + timedelta(days=i)
                params = {"country": "US", "date": day.isoformat()}
                async with session.get("https://api.tvmaze.com/schedule", params=params) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    for entry in data:
                        show = entry.get("show", {})
                        if not show:
                            continue
                        genres = [g.lower() for g in show.get("genres", [])]
                        if any(g in exclude_genres for g in genres):
                            continue
                        # Only include if this is a series premiere (season 1, episode 1) or season premiere (episode 1)
                        season = entry.get("season")
                        episode = entry.get("number")
                        airdate = entry.get("airdate")
                        name = show.get("name", "Untitled")
                        key = (name.lower(), season, airdate)
                        if episode == 1 and key not in seen:
                            shows.append({
                                "name": name,
                                "season": season,
                                "airdate": airdate,
                                "type": "new" if season == 1 else "season",
                                "rating": show.get("rating", {}).get("average", "N/A"),
                                "popularity": show.get("weight", 0),
                            })
                            seen.add(key)
                        if len(shows) >= max_results:
                            break
                if len(shows) >= max_results:
                    break
        return shows

    # Global set for highlight series (user can add to this at runtime)
    highlight_titles = set([
        "love death robots",
        "last of us",
        "black mirror",
        "walking dead",
        "severance",
        "you",
        "daredevil: born again",
        "rick & morty",
        "rick and morty",
        "the umbrella academy",
        "the witcher",
        "euphoria",
        "harley quinn",
        "loki",
        "stranger things",
        "arcane"
    ])

    highlight_movies = set([
        "dune",
        "oppenheimer",
        "barbie",
        "spider-man: across the spider-verse",
        "the marvels",
        "wonka",
        "killers of the flower moon",
        "the hunger games: the ballad of songbirds & snakes",
        "napoleon",
        "the creator"
    ])
    favourite_series = set()
    favourite_movies = set()

    HIGHLIGHT_LISTS_FILE = "highlight_lists.json"

    def load_highlight_lists():
        if os.path.exists(HIGHLIGHT_LISTS_FILE):
            with open(HIGHLIGHT_LISTS_FILE, "r") as f:
                data = json.load(f)
                return (
                    set(data.get("series", [])),
                    set(data.get("movies", [])),
                    set(data.get("favourite_series", [])),
                    set(data.get("favourite_movies", [])),
                )
        return None, None, None, None

    def save_highlight_lists():
        with open(HIGHLIGHT_LISTS_FILE, "w") as f:
            json.dump({
                "series": list(highlight_titles),
                "movies": list(highlight_movies),
                "favourite_series": list(favourite_series),
                "favourite_movies": list(favourite_movies)
            }, f)

    async def addseries(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /addseries [series name]")
            return ConversationHandler.END
        query = " ".join(context.args).strip()
        # Search TMDB for matching series
        results = await search_tmdb(query=query, media_type="tv", max_results=5)
        if not results:
            await update.message.reply_text("No matching series found.")
            return ConversationHandler.END
        msg = "Please choose the correct series by replying with the number:\n"
        for idx, show in enumerate(results, 1):
            name = show.get("name", "Untitled")
            year = show.get("first_air_date", "TBA")[:4]
            network = show.get("network", show.get("origin_country", ["?"])[0])
            msg += f"{idx}. {name} ({year}) - {network}\n"
        user_addseries_context[update.effective_chat.id] = results
        await update.message.reply_text(msg)
        return ADD_SERIES_CHOICE

    async def addseries_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        results = user_addseries_context.get(chat_id)
        if not results:
            await update.message.reply_text("No series selection in progress. Use /addseries [title] to start.")
            return ConversationHandler.END
        try:
            choice = int(update.message.text.strip())
            if not (1 <= choice <= len(results)):
                raise ValueError
        except ValueError:
            await update.message.reply_text("Invalid choice. Please reply with a number from the list.")
            return ADD_SERIES_CHOICE
        show = results[choice-1]
        name = show.get("name", "Untitled")
        year = show.get("first_air_date", "TBA")[:4]
        entry = f"{name} ({year})"
        highlight_titles.add(entry.lower())
        save_highlight_lists()
        await update.message.reply_text(f"Added '{entry}' to your highlight series list.")
        user_addseries_context.pop(chat_id, None)
        return ConversationHandler.END

    async def addmovie(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /addmovie [movie name]")
            return ConversationHandler.END
        query = " ".join(context.args).strip()
        results = await search_tmdb(query=query, media_type="movie", max_results=5)
        if not results:
            await update.message.reply_text("No matching movies found.")
            return ConversationHandler.END
        msg = "Please choose the correct movie by replying with the number:\n"
        for idx, movie in enumerate(results, 1):
            title = movie.get("title", "Untitled")
            year = movie.get("release_date", "TBA")[:4]
            studio = movie.get("production_companies", [{}])[0].get("name", "?")
            msg += f"{idx}. {title} ({year}) - {studio}\n"
        user_addmovie_context[update.effective_chat.id] = results
        await update.message.reply_text(msg)
        return ADD_MOVIE_CHOICE

    async def addmovie_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        results = user_addmovie_context.get(chat_id)
        if not results:
            await update.message.reply_text("No movie selection in progress. Use /addmovie [title] to start.")
            return ConversationHandler.END
        try:
            choice = int(update.message.text.strip())
            if not (1 <= choice <= len(results)):
                raise ValueError
        except ValueError:
            await update.message.reply_text("Invalid choice. Please reply with a number from the list.")
            return ADD_MOVIE_CHOICE
        movie = results[choice-1]
        title = movie.get("title", "Untitled")
        year = movie.get("release_date", "TBA")[:4]
        entry = f"{title} ({year})"
        highlight_movies.add(entry.lower())
        save_highlight_lists()
        await update.message.reply_text(f"Added '{entry}' to your highlight movies list.")
        user_addmovie_context.pop(chat_id, None)
        return ConversationHandler.END

    NOTIFY_INTERVAL = 24 * 60 * 60  # 24 hours in seconds (daily)
    NOTIFY_LOOKAHEAD_DAYS = 3  # Notify if release is within 3 days

    async def notify_releases(context: ContextTypes.DEFAULT_TYPE):
        # Check for upcoming releases in highlight lists
        now = get_utc_today()
        cutoff = now + timedelta(days=NOTIFY_LOOKAHEAD_DAYS)
        chat_id = context.job.chat_id
        # Series
        upcoming_series = []
        async with aiohttp.ClientSession() as session:
            for highlight in highlight_titles:
                url = f"https://api.themoviedb.org/3/search/tv"
                params = {"api_key": TMDB_API_KEY, "language": "en-US", "query": highlight}
                data = await fetch_json(session, url, params)
                for show in data.get('results', []):
                    tv_id = show.get('id')
                    details_url = f"https://api.themoviedb.org/3/tv/{tv_id}"
                    details = await fetch_json(session, details_url, {"api_key": TMDB_API_KEY, "language": "en-US"})
                    name = details.get('name', '').lower()
                    if name != highlight:
                        continue
                    for season in details.get('seasons', []):
                        air_date = season.get('air_date')
                        season_number = season.get('season_number')
                        if air_date and season_number:
                            try:
                                airdate_obj = datetime.strptime(air_date, "%Y-%m-%d").date()
                            except Exception:
                                airdate_obj = None
                            if airdate_obj and now <= airdate_obj <= cutoff:
                                label = f"Season {season_number}"
                                upcoming_series.append(f"<b>{html.escape(details.get('name'))}</b> - {label} releases on <b>{air_date}</b>")
        # Movies
        upcoming_movies = []
        for highlight in highlight_movies:
            url = f"https://api.themoviedb.org/3/search/movie"
            params = {"api_key": TMDB_API_KEY, "language": "en-US", "query": highlight}
            async with aiohttp.ClientSession() as session:
                data = await fetch_json(session, url, params)
                for movie in data.get('results', []):
                    title = movie.get('title', '').lower()
                    if title != highlight:
                        continue
                    release_date = movie.get('release_date')
                    if release_date:
                        try:
                            release_obj = datetime.strptime(release_date, "%Y-%m-%d").date()
                        except Exception:
                            release_obj = None
                        if release_obj and now <= release_obj <= cutoff:
                            upcoming_movies.append(f"<b>{html.escape(movie.get('title'))}</b> releases on <b>{release_date}</b>")
        # Send notification if any
        if upcoming_series or upcoming_movies:
            msg = "<b>Upcoming Releases:</b>\n"
            if upcoming_series:
                msg += "\n".join(upcoming_series) + "\n"
            if upcoming_movies:
                msg += "\n".join(upcoming_movies)
            await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='HTML')

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        await update.message.reply_text(
            f"Hello {user.first_name}! 🤖\n"
            "Use /movies or /series to see upcoming movies or your highlight TV series.\n"
            "Use /addseries [title] to add a new series to your highlight list.\n"
            "Use /chatid to get your chat ID.\n"
            "Use /help to see all commands.\n\n"
            "To get daily release notifications, use /notifyon. To stop, use /notifyoff.",
            parse_mode='HTML')

    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "<b>Available Commands</b>\n"
            "====================\n\n"
            "<b>General</b>\n"
            "/start - Show welcome message and your highlight series list.\n"
            "/series - Show new/returning seasons for your highlight series in the next 120 days.\n"
            "/addseries [title] - Add a new series to your highlight list.\n"
            "/movies - Show upcoming movies in the next 30 days.\n"
            "/chatid - Show your chat ID.\n"
            "/help - Show this help message.\n"
            "/listseries - List all your highlight series.\n"
            "/listmovies - List all your highlight movies.\n"
            "/removeseries [title] - Remove a series from your highlight list.\n"
            "/removemovie [title] - Remove a movie from your highlight list.\n"
            "/randomseries - Pick a random series from your highlight list.\n"
            "/randommovie - Pick a random movie from your highlight list.\n"
            "/trendingseries - Show trending TV series.\n"
            "/trendingmovies - Show trending movies.\n"
            "/topseries - Show top-rated TV series.\n"
            "/topmovies - Show top-rated movies.\n\n"
            "<b>Favourites</b>\n"
            "/addfaveseries [series name] - Add a series to your favourites.\n"
            "/addfavemovie [movie name] - Add a movie to your favourites.\n"
            "/removefaveseries [series name] - Remove a series from your favourites.\n"
            "/removefavemovie [movie name] - Remove a movie from your favourites.\n"
            "/listfaveseries - List all your favourite series.\n"
            "/listfavemovies - List all your favourite movies.",
            parse_mode='HTML')

    async def series(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Fetching new/returning seasons for your highlight series in the next 120 days...")
        try:
            now = get_utc_today()
            cutoff = now + timedelta(days=120)
            messages = []
            shows_to_display = []
            # Only process highlight_titles
            async with aiohttp.ClientSession() as session:
                for highlight in highlight_titles:
                    url = f"https://api.themoviedb.org/3/search/tv"
                    params = {"api_key": TMDB_API_KEY, "language": "en-US", "query": highlight}
                    data = await fetch_json(session, url, params)
                    for show in data.get('results', []):
                        tv_id = show.get('id')
                        details_url = f"https://api.themoviedb.org/3/tv/{tv_id}"
                        details = await fetch_json(session, details_url, {"api_key": TMDB_API_KEY, "language": "en-US"})
                        name = details.get('name', '').lower()
                        if name != highlight:
                            continue
                        # New season
                        for season in details.get('seasons', []):
                            air_date = season.get('air_date')
                            season_number = season.get('season_number')
                            if air_date and season_number and (season_number == 1 or season_number > 1):
                                try:
                                    airdate_obj = datetime.strptime(air_date, "%Y-%m-%d").date()
                                except Exception:
                                    airdate_obj = None
                                if airdate_obj and now <= airdate_obj <= cutoff:
                                    show_type = 'new' if season_number == 1 else f'season_{season_number}'
                                    shows_to_display.append((details, show_type, air_date, True))
                                    break
            # Deduplicate by (name.lower(), show_type, air_date)
            deduped = {}
            for details, show_type, air_date, force_highlight in shows_to_display:
                name = details.get('name', 'Untitled')
                key = (name.lower(), show_type, air_date)
                if key not in deduped:
                    deduped[key] = (details, show_type, air_date, force_highlight)
            sorted_shows = sorted(
                deduped.values(),
                key=lambda x: (
                    -int(x[0].get('popularity', 0) or 0),
                    x[2] or x[0].get('first_air_date', '')
                )
            )
            for details, show_type, air_date, force_highlight in sorted_shows:
                name = details.get('name', 'Untitled')
                rating = details.get('vote_average', 'N/A')
                pop = details.get('popularity', 0)
                if show_type == 'new':
                    emoji = "🆕"
                    label = "Premiere"
                    date_val = details.get('first_air_date', 'TBA')
                elif show_type.startswith('season_'):
                    emoji = "🌟"
                    label = f"Season {show_type.split('_')[1]} Premiere"
                    date_val = air_date
                else:
                    emoji = "❓"
                    label = show_type
                    date_val = air_date
                emoji = "✨" + emoji
                msg = f"{emoji} <b>{html.escape(name)}</b>\n📅 {label}: <b>{date_val}</b>\n⭐ Rating: <b>{rating}</b>\n🔥 Popularity: <b>{int(pop) if pop is not None else 'N/A'}</b>"
                messages.append(msg)
            if not messages:
                await update.message.reply_text("No new or returning seasons found for your highlight series in the next 120 days.")
                return
            reply = "<b>New & Returning Seasons (Next 120 Days):</b>\n\n" + "\n\n".join(messages)
            await update.message.reply_text(reply, parse_mode='HTML')
        except Exception as e:
            logger.error("Error searching series", exc_info=True)
            await update.message.reply_text("Sorry, an error occurred while searching TV series.")

    async def chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(f"Your chat ID is: {update.effective_chat.id}")

    async def movies(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Fetching upcoming movies...")
        try:
            results = await search_tmdb(media_type="movie")
            if not results:
                await update.message.reply_text("No upcoming movies found.")
                return
            messages = []
            for movie in results:
                title = movie.get("title")
                release_date = movie.get("release_date")
                rating = movie.get("vote_average")
                popularity = movie.get("popularity")
                msg = f"🎬 <b>{html.escape(title)}</b>\n📅 Release Date: <b>{release_date}</b>\n⭐ Rating: <b>{rating}</b>\n🔥 Popularity: <b>{popularity}</b>"
                messages.append(msg)
            reply = "<b>Upcoming Movies:</b>\n\n" + "\n\n".join(messages)
            await update.message.reply_text(reply, parse_mode='HTML')
        except Exception as e:
            logger.error("Error fetching movies", exc_info=True)
            await update.message.reply_text("Sorry, an error occurred while fetching movie data.")

    async def listseries(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not highlight_titles:
            await update.message.reply_text("Your highlight series list is empty.")
            return
        highlight_list = '\n'.join(f"- <b>{html.escape(title.title())}</b>" for title in sorted(highlight_titles))
        await update.message.reply_text(f"<b>Your Highlight Series List:</b>\n{highlight_list}", parse_mode='HTML')

    async def listmovies(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not highlight_movies:
            await update.message.reply_text("Your highlight movies list is empty.")
            return
        movie_list = '\n'.join(f"- <b>{html.escape(title.title())}</b>" for title in sorted(highlight_movies))
        await update.message.reply_text(f"<b>Your Highlight Movies List:</b>\n{movie_list}", parse_mode='HTML')

    async def removeseries(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /removeseries [title]")
            return
        title = " ".join(context.args).strip().lower()
        if title not in highlight_titles:
            await update.message.reply_text(f"'{html.escape(title.title())}' is not in your highlight series list.")
            return
        highlight_titles.remove(title)
        save_highlight_lists()
        await update.message.reply_text(f"Removed '{html.escape(title.title())}' from your highlight series list.")

    async def removemovie(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /removemovie [title]")
            return
        title = " ".join(context.args).strip().lower()
        if title not in highlight_movies:
            await update.message.reply_text(f"'{html.escape(title.title())}' is not in your highlight movies list.")
            return
        highlight_movies.remove(title)
        save_highlight_lists()
        await update.message.reply_text(f"Removed '{html.escape(title.title())}' from your highlight movies list.")

    async def addmovie(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /addmovie <movie name>")
            return ConversationHandler.END
        query = " ".join(context.args).strip()
        results = await search_tmdb(query=query, media_type="movie", max_results=5)
        if not results:
            await update.message.reply_text("No matching movies found.")
            return ConversationHandler.END
        msg = "Please choose the correct movie by replying with the number:\n"
        for idx, movie in enumerate(results, 1):
            title = movie.get("title", "Untitled")
            year = movie.get("release_date", "TBA")[:4]
            studio = movie.get("production_companies", [{}])[0].get("name", "?")
            msg += f"{idx}. {title} ({year}) - {studio}\n"
        user_addmovie_context[update.effective_chat.id] = results
        await update.message.reply_text(msg)
        return ADD_MOVIE_CHOICE

    async def randomseries(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Picking a random TV series from TMDB...")
        try:
            # Get a random page and random result from TMDB popular TV
            import random
            page = random.randint(1, 100)  # TMDB allows up to 500 pages
            base_url = "https://api.themoviedb.org/3/tv/popular"
            async with aiohttp.ClientSession() as session:
                params = {"api_key": TMDB_API_KEY, "language": "en-US", "page": page}
                data = await fetch_json(session, base_url, params)
                shows = data.get("results", [])
                if not shows:
                    await update.message.reply_text("No series found.")
                    return
                pick = random.choice(shows)
                name = pick.get("name", "Untitled")
                date = pick.get("first_air_date", "TBA")
                poster = pick.get("poster_path")
                poster_url = f"https://image.tmdb.org/t/p/w200{poster}" if poster else None
                msg = f"<b>{html.escape(name)}</b> ({date})"
                if poster_url:
                    msg += f"\n<a href='{poster_url}'>Poster</a>"
                await update.message.reply_text(msg, parse_mode='HTML', disable_web_page_preview=False)
        except Exception as e:
            logger.error("Error in randomseries", exc_info=True)
            await update.message.reply_text("Sorry, an error occurred while picking a random series.")

    async def randommovie(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Picking a random movie from TMDB...")
        try:
            import random
            page = random.randint(1, 100)
            base_url = "https://api.themoviedb.org/3/movie/popular"
            async with aiohttp.ClientSession() as session:
                params = {"api_key": TMDB_API_KEY, "language": "en-US", "page": page}
                data = await fetch_json(session, base_url, params)
                movies = data.get("results", [])
                if not movies:
                    await update.message.reply_text("No movies found.")
                    return
                pick = random.choice(movies)
                title = pick.get("title", "Untitled")
                date = pick.get("release_date", "TBA")
                poster = pick.get("poster_path")
                poster_url = f"https://image.tmdb.org/t/p/w200{poster}" if poster else None
                msg = f"<b>{html.escape(title)}</b> ({date})"
                if poster_url:
                    msg += f"\n<a href='{poster_url}'>Poster</a>"
                await update.message.reply_text(msg, parse_mode='HTML', disable_web_page_preview=False)
        except Exception as e:
            logger.error("Error in randommovie", exc_info=True)
            await update.message.reply_text("Sorry, an error occurred while picking a random movie.")

    async def trendingseries(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Fetching trending TV series...")
        try:
            results = await fetch_trending_tv_shows()
            if not results:
                await update.message.reply_text("No trending TV series found.")
                return
            messages = []
            for show in results:
                name = show.get("name", "Untitled")
                date = show.get("first_air_date", "TBA")
                poster = show.get("poster_path")
                poster_url = f"https://image.tmdb.org/t/p/w200{poster}" if poster else None
                msg = f"<b>{html.escape(name)}</b> ({date})"
                if poster_url:
                    msg += f" | <a href='{poster_url}'>Poster</a>"
                messages.append(msg)
            reply = "<b>Trending TV Series:</b>\n" + "\n".join(messages)
            await update.message.reply_text(reply, parse_mode='HTML', disable_web_page_preview=False)
        except Exception as e:
            logger.error("Error fetching trending series", exc_info=True)
            await update.message.reply_text("Sorry, an error occurred while fetching trending TV series.")

    async def trendingmovies(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Fetching trending movies...")
        try:
            results = await fetch_trending_tv_shows(media_type="movie")
            if not results:
                await update.message.reply_text("No trending movies found.")
                return
            messages = []
            for movie in results:
                title = movie.get("title", "Untitled")
                release_date = movie.get("release_date", "TBA")
                poster = movie.get("poster_path")
                poster_url = f"https://image.tmdb.org/t/p/w200{poster}" if poster else None
                msg = f"<b>{html.escape(title)}</b> ({release_date})"
                if poster_url:
                    msg += f" | <a href='{poster_url}'>Poster</a>"
                messages.append(msg)
            reply = "<b>Trending Movies:</b>\n" + "\n".join(messages)
            await update.message.reply_text(reply, parse_mode='HTML', disable_web_page_preview=False)
        except Exception as e:
            logger.error("Error fetching trending movies", exc_info=True)
            await update.message.reply_text("Sorry, an error occurred while fetching trending movies.")

    async def topseries(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Fetching top-rated TV series...")
        try:
            results = await fetch_trending_tv_shows(max_results=10)  # Reusing function for simplicity
            if not results:
                await update.message.reply_text("No top-rated TV series found.")
                return
            messages = []
            for show in results:
                name = show.get("name", "Untitled")
                date = show.get("first_air_date", "TBA")
                poster = show.get("poster_path")
                poster_url = f"https://image.tmdb.org/t/p/w200{poster}" if poster else None
                msg = f"<b>{html.escape(name)}</b> ({date})"
                if poster_url:
                    msg += f" | <a href='{poster_url}'>Poster</a>"
                messages.append(msg)
            reply = "<b>Top-Rated TV Series:</b>\n" + "\n".join(messages)
            await update.message.reply_text(reply, parse_mode='HTML', disable_web_page_preview=False)
        except Exception as e:
            logger.error("Error fetching top series", exc_info=True)
            await update.message.reply_text("Sorry, an error occurred while fetching top-rated TV series.")

    async def topmovies(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Fetching top-rated movies...")
        try:
            results = await fetch_trending_tv_shows(media_type="movie", max_results=10)  # Reusing function
            if not results:
                await update.message.reply_text("No top-rated movies found.")
                return
            messages = []
            for movie in results:
                title = movie.get("title", "Untitled")
                release_date = movie.get("release_date", "TBA")
                poster = movie.get("poster_path")
                poster_url = f"https://image.tmdb.org/t/p/w200{poster}" if poster else None
                msg = f"<b>{html.escape(title)}</b> ({release_date})"
                if poster_url:
                    msg += f" | <a href='{poster_url}'>Poster</a>"
                messages.append(msg)
            reply = "<b>Top-Rated Movies:</b>\n" + "\n".join(messages)
            await update.message.reply_text(reply, parse_mode='HTML', disable_web_page_preview=False)
        except Exception as e:
            logger.error("Error fetching top movies", exc_info=True)
            await update.message.reply_text("Sorry, an error occurred while fetching top-rated movies.")
    ADD_SERIES_CHOICE = 0
    ADD_MOVIE_CHOICE = 1
    user_addseries_context = {}
    user_addmovie_context = {}

    # Notification command handlers must be defined before __main__
    async def notifyon(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        job_queue = getattr(context.application, 'job_queue', None)
        if job_queue is None:
            await update.message.reply_text("❌ JobQueue is not available. Please ensure the bot is started with job_queue enabled.")
            return
        # Remove any existing job for this chat
        current_jobs = job_queue.get_jobs_by_name(str(chat_id))
        for job in current_jobs:
            job.schedule_removal()
        # Schedule a new daily job
        job_queue.run_repeating(
            notify_releases,
            interval=NOTIFY_INTERVAL,
            first=0,  # Run immediately, then every 24h
            chat_id=chat_id,
            name=str(chat_id),
        )
        await update.message.reply_text("🔔 Daily release notifications enabled! You'll get a message when a highlight series or movie is about to be released.")

    async def notifyoff(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        job_queue = getattr(context.application, 'job_queue', None)
        if job_queue is None:
            await update.message.reply_text("❌ JobQueue is not available. Please ensure the bot is started with job_queue enabled.")
            return
        current_jobs = job_queue.get_jobs_by_name(str(chat_id))
        for job in current_jobs:
            job.schedule_removal()
        await update.message.reply_text("🔕 Daily release notifications disabled.")

    async def addfaveseries(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /addfaveseries [series name]")
            return
        name = " ".join(context.args).strip()
        if not name:
            await update.message.reply_text("Please provide a valid series name.")
            return
        # Split by '+' and add each series separately
        series_list = [s.strip() for s in name.split('+') if s.strip()]
        added = []
        already = []
        for entry in series_list:
            if entry.lower() in (s.lower() for s in favourite_series):
                already.append(entry)
            else:
                favourite_series.add(entry)
                added.append(entry)
        save_highlight_lists()
        msg = ""
        if added:
            msg += "Added to your favourite series list:\n" + "\n".join(f"- {a}" for a in added)
        if already:
            msg += ("\n" if msg else "") + "Already in your favourite series list:\n" + "\n".join(f"- {a}" for a in already)
        if not msg:
            msg = "No valid series names provided."
        await update.message.reply_text(msg)

    async def addfavemovie(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /addfavemovie [movie name]")
            return
        name = " ".join(context.args).strip()
        if not name:
            await update.message.reply_text("Please provide a valid movie name.")
            return
        # Split by '+' and add each movie separately
        movies = [m.strip() for m in name.split('+') if m.strip()]
        added = []
        already = []
        for entry in movies:
            if entry.lower() in (m.lower() for m in favourite_movies):
                already.append(entry)
            else:
                favourite_movies.add(entry)
                added.append(entry)
        save_highlight_lists()
        msg = ""
        if added:
            msg += "Added to your favourite movies list:\n" + "\n".join(f"- {a}" for a in added)
        if already:
            msg += ("\n" if msg else "") + "Already in your favourite movies list:\n" + "\n".join(f"- {a}" for a in already)
        if not msg:
            msg = "No valid movie names provided."
        await update.message.reply_text(msg)

    async def removefaveseries(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /removefaveseries [series name]")
            return
        name = " ".join(context.args).strip()
        found = None
        for s in favourite_series:
            if s.lower() == name.lower():
                found = s
                break
        if not found:
            await update.message.reply_text(f"'{name}' is not in your favourite series list.")
            return
        favourite_series.remove(found)
        save_highlight_lists()
        await update.message.reply_text(f"Removed '{found}' from your favourite series list.")

    async def removefavemovie(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /removefavemovie [movie name]")
            return
        name = " ".join(context.args).strip()
        found = None
        for m in favourite_movies:
            if m.lower() == name.lower():
                found = m
                break
        if not found:
            await update.message.reply_text(f"'{name}' is not in your favourite movies list.")
            return
        favourite_movies.remove(found)
        save_highlight_lists()
        await update.message.reply_text(f"Removed '{found}' from your favourite movies list.")

    async def listfaveseries(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not favourite_series:
            await update.message.reply_text("Your favourite series list is empty.")
            return
        sorted_list = sorted(favourite_series, key=lambda x: x.lower())
        msg = '\n'.join(f"- <b>{html.escape(s)}</b>" for s in sorted_list)
        await update.message.reply_text(f"<b>Your Favourite Series List:</b>\n{msg}", parse_mode='HTML')

    async def listfavemovies(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not favourite_movies:
            await update.message.reply_text("Your favourite movies list is empty.")
            return
        sorted_list = sorted(favourite_movies, key=lambda x: x.lower())
        msg = '\n'.join(f"- <b>{html.escape(m)}</b>" for m in sorted_list)
        await update.message.reply_text(f"<b>Your Favourite Movies List:</b>\n{msg}", parse_mode='HTML')

    if __name__ == "__main__":
        # Load highlight lists from file if available
        loaded_series, loaded_movies, loaded_faveseries, loaded_favemovies = load_highlight_lists()
        if loaded_series is not None:
            highlight_titles = loaded_series
        if loaded_movies is not None:
            highlight_movies = loaded_movies
        if loaded_faveseries is not None:
            favourite_series = loaded_faveseries
        if loaded_favemovies is not None:
            favourite_movies = loaded_favemovies

        app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("chatid", chatid))
        app.add_handler(CommandHandler("movies", movies))
        app.add_handler(CommandHandler("series", series))
        app.add_handler(CommandHandler("help", help_command))
        app.add_handler(CommandHandler("listseries", listseries))
        app.add_handler(CommandHandler("listmovies", listmovies))
        app.add_handler(CommandHandler("removeseries", removeseries))
        app.add_handler(CommandHandler("removemovie", removemovie))
        app.add_handler(CommandHandler("randomseries", randomseries))
        app.add_handler(CommandHandler("randommovie", randommovie))
        app.add_handler(CommandHandler("trendingseries", trendingseries))
        app.add_handler(CommandHandler("trendingmovies", trendingmovies))
        app.add_handler(CommandHandler("topseries", topseries))
        app.add_handler(CommandHandler("topmovies", topmovies))
        app.add_handler(CommandHandler("notifyon", notifyon))
        app.add_handler(CommandHandler("notifyoff", notifyoff))
        # Favourite commands
        app.add_handler(CommandHandler("addfaveseries", addfaveseries))
        app.add_handler(CommandHandler("addfavemovie", addfavemovie))
        app.add_handler(CommandHandler("removefaveseries", removefaveseries))
        app.add_handler(CommandHandler("removefavemovie", removefavemovie))
        app.add_handler(CommandHandler("listfaveseries", listfaveseries))
        app.add_handler(CommandHandler("listfavemovies", listfavemovies))

        # Conversation handler setup for addseries and addmovie
        addseries_conv = ConversationHandler(
            entry_points=[CommandHandler("addseries", addseries)],
            states={
                ADD_SERIES_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, addseries_choice)],
            },
            fallbacks=[],
        )
        addmovie_conv = ConversationHandler(
            entry_points=[CommandHandler("addmovie", addmovie)],
            states={
                ADD_MOVIE_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, addmovie_choice)],
            },
            fallbacks=[],
        )
        app.add_handler(addseries_conv)
        app.add_handler(addmovie_conv)

        print("Bot is running. Press Ctrl+C to stop.")
        app.run_polling()
except Exception as e:
    import traceback
    print('Startup error:', e, file=sys.stderr)
    traceback.print_exc()
    raise