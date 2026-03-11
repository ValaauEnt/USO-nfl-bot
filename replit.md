# USO NFL Discord Bot

A Discord bot for tracking live NFL scores, news, player stats, game logs, and trade headlines. Data is sourced from ESPN's public APIs with NFL.com and Yahoo Sports as fallbacks.

## Features

- `/scoreboard` — Live NFL scores for the current week, updated every 45 seconds
- `/gamestats <team>` — Stat leaders for a specific game (by team abbreviation)
- `/playerstats <name>` — Player stats with autocomplete search
- `/gamelog <name>` — Paginated game-by-game log for a player
- `/headlines` — Latest NFL headlines
- `/recenttrades` — Recent trade-related news
- `/tradetracker` — Trade headlines categorized as completed, rumored, or other
- Auto-post scores and news to configured channels (optional)
- Score change alerts posted to a configurable alerts channel
- AI-powered player profile enrichment via OpenAI when ESPN data is incomplete

## Setup

### Required Secrets
- `DISCORD_TOKEN` — Your Discord bot token (required to run)
- `OPENAI_API_KEY` — Optional. Enables AI fallback for incomplete player profiles

### Optional Channel IDs (edit main.py)
Set these to Discord channel IDs to enable auto-posting:
- `SCORES_CHANNEL_ID` — Auto-updates live scores every 45 seconds
- `NEWS_CHANNEL_ID` — Auto-posts headlines every 10 minutes
- `ALERTS_CHANNEL_ID` — Posts score change and final game alerts

## Architecture

- **main.py** — Single-file bot with all logic
- Data sources: ESPN scoreboard, news, athlete, and summary APIs
- Fallback scrapers for NFL.com and Yahoo Sports
- Player index built on startup from ESPN athletes endpoint (~20,000 players)
- AI enrichment: OpenAI Responses API with structured JSON output to fill missing player profiles

## Dependencies

- `discord.py` — Discord bot framework
- `aiohttp` — Async HTTP client
- `beautifulsoup4` — HTML scraping for fallback news sources
- `openai` — Optional AI enrichment for player profiles

## Running

The bot runs via the "Start application" workflow (`python main.py`). It requires `DISCORD_TOKEN` to be set as a secret.
