<!-- FILEPATH: /home/cameron/Desktop/moviebot/README.md -->

<h1 align="center">🎬 Telegram MovieBot</h1>
<p align="center">
  <b>Your personal Telegram assistant for tracking, highlighting, and getting notified about movies & TV series!</b><br>
  <i>Built with Python & python-telegram-bot</i>
</p>

---

## ✨ Features

- <b>Upcoming Movies & TV Series</b>: Instantly see what's coming soon.
- <b>Highlight Lists</b>: Curate your own must-watch lists for movies and series.
- <b>Favourites</b>: Mark your all-time favourites for quick access.
- <b>Daily Notifications</b>: Get Telegram alerts for releases in your highlight lists.
- <b>Trending & Top-Rated</b>: Discover what's hot and highly rated.
- <b>Google Calendar Integration</b>: <i>(Optional)</i> Add releases to your Google Calendar.

---

## 🚀 Getting Started

### 1. Clone the Repository
```sh
git clone https://github.com/yourusername/telegram-moviebot.git
cd telegram-moviebot
```

### 2. Set Up Python Environment
```sh
python3 -m venv .venv
source .venv/bin/activate.fish  # (for fish shell)
pip install -r requirements.txt
```

### 3. Configure API Keys
Create a `.env` file in the project root (already done):
```env
TELEGRAM_TOKEN=your-telegram-bot-token
TMDB_API_KEY=your-tmdb-api-key
OMDB_API_KEY=your-omdb-api-key
TVMAZE_API_KEY=your-tvmaze-api-key
```
- Get a Telegram bot token from [@BotFather](https://t.me/BotFather)
- Get a TMDB API key from [themoviedb.org](https://www.themoviedb.org/)
- (Optional) Get OMDb and TVmaze API keys for extra features

### 4. Run the Bot
```sh
python main.py
```

---

## 💡 Usage

| Command                | Description                                 |
|-----------------------|---------------------------------------------|
| `/start`              | Welcome message and help                    |
| `/movies`             | List upcoming movies                        |
| `/series`             | List new/returning TV series                |
| `/addseries [title]`  | Add a series to your highlight list         |
| `/addmovie [title]`   | Add a movie to your highlight list          |
| `/listseries`         | List your highlight series                  |
| `/listmovies`         | List your highlight movies                  |
| `/removeseries [title]`| Remove a series from your highlight list   |
| `/removemovie [title]`| Remove a movie from your highlight list     |
| `/addfaveseries [name]`| Add a series to favourites                 |
| `/addfavemovie [name]`| Add a movie to favourites                   |
| `/listfaveseries`     | List your favourite series                  |
| `/listfavemovies`     | List your favourite movies                  |
| `/notifyon`           | Enable daily notifications                  |
| `/notifyoff`          | Disable notifications                       |
| `/trendingseries`     | Trending TV series                          |
| `/trendingmovies`     | Trending movies                             |
| `/topseries`          | Top-rated TV series                         |
| `/topmovies`          | Top-rated movies                            |

---

## 📅 Google Calendar Integration (Optional)
- Place your `credentials.json` in the project root (see Google Calendar API docs).
- The bot will prompt you to authenticate on first use.

---

## 🔒 Security & Open Source Notes
- <b>No secrets are stored in code.</b> All API keys are loaded from `.env` (which is in `.gitignore`).
- <b>Never</b> commit your `.env`, `token.json`, or `credentials.json` to public repositories.

---

## 🤝 Contributing
Pull requests and suggestions are welcome! Please open an issue or PR.

---

## 🪪 License
MIT License
