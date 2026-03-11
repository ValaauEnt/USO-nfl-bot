# USO NFL Discord Bot

A Discord bot for tracking live NFL scores, news, player stats, game logs, and trade headlines. Data is sourced from ESPN's public APIs with NFL.com and Yahoo Sports as fallbacks.

## Commands

- `/scoreboard` — Live NFL scores for the current week, with Prev/Next week and Regular Season/Playoffs toggle
- `/gamestats <team>` — Stat leaders for a specific live game (by team abbreviation)
- `/playerstats <name>` — Player stats with autocomplete search and season navigation
- `/gamelog <name>` — Paginated game-by-game log for a player
- `/seasonstats <name>` — Season totals with year buttons and game log toggle
- `/headlines` — Latest NFL headlines
- `/tradetracker` — Trade headlines categorized as Completed, Rumors, or Other
- `/nflwatch` — NFL trades, contracts, and roster moves market watch
- `/nfl-leaders` — Offensive and defensive stat leaders with toggle buttons

## Setup

### Required Secrets
- `DISCORD_TOKEN` — Your Discord bot token (required to run)

### Optional Channel IDs (edit main.py)
Set these to Discord channel IDs to enable auto-posting:
- `SCORES_CHANNEL_ID` — Auto-updates live scores every 45 seconds
- `NEWS_CHANNEL_ID` — Auto-posts headlines every 10 minutes
- `ALERTS_CHANNEL_ID` — Posts score change and final game alerts
- `NFLWATCH_CHANNEL_ID` — Auto-posts NFL market watch at 8am and 5pm ET daily

## Architecture

- **main.py** — Single-file bot with all logic
- Data sources: ESPN scoreboard, news, athlete, gamelog, and leaders APIs
- Fallback scrapers for NFL.com and Yahoo Sports
- Player index built on startup from all 32 team rosters (~2,496 active players)
- Player pipeline: name search → athlete ID → profile + gamelog fetched concurrently → merged result
- Scheduled auto-posts use `discord.ext.tasks` with Eastern timezone support via `zoneinfo`

## Dependencies

- `discord.py` — Discord bot framework
- `aiohttp` — Async HTTP client
- `beautifulsoup4` — HTML scraping for fallback news sources

## Running

The bot runs via the "Start application" workflow (`python main.py`). It requires `DISCORD_TOKEN` to be set as a secret. Deployed as a VM (always-on) so the bot stays connected 24/7.
