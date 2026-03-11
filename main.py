import os
import re
import html
import aiohttp
import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

TOKEN = os.getenv("DISCORD_TOKEN")

# Optional auto-post channels. Set to your Discord channel ID to enable.
SCORES_CHANNEL_ID = 0
NEWS_CHANNEL_ID = 0
ALERTS_CHANNEL_ID = 0
NFLWATCH_CHANNEL_ID = 1480936006395101387  # Auto-posts NFL market watch at 8am and 5pm ET daily

# ESPN
ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
ESPN_NEWS_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news"
ESPN_SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={event_id}"
ESPN_TEAM_ROSTER_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{team}/roster"

# ESPN uses different URL slugs for some teams
ROSTER_SLUGS = {
    "WAS": "wsh",
}
ESPN_ATHLETE_PROFILE_URL = "https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/athletes/{athlete_id}"
ESPN_ATHLETE_GAMELOG_URL = "https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/athletes/{athlete_id}/gamelog"
ESPN_LEADERS_URL = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/{year}/types/{stype}/leaders"

_LEADERS_OFFENSE = [
    "Passing Yards", "Passing Touchdowns", "Quarterback Rating",
    "Rushing Yards", "Rushing Touchdowns",
    "Receiving Yards", "Receptions", "Receiving Touchdowns",
]
_LEADERS_DEFENSE = [
    "Total Tackles", "Sacks", "Interceptions", "Passes Defended",
]

# Fallback pages
NFL_NEWS_URL = "https://www.nfl.com/news/"
YAHOO_NFL_NEWS_URL = "https://sports.yahoo.com/nfl/news/"

TEAM_LOGOS = {
    "ARI": "https://a.espncdn.com/i/teamlogos/nfl/500/ari.png",
    "ATL": "https://a.espncdn.com/i/teamlogos/nfl/500/atl.png",
    "BAL": "https://a.espncdn.com/i/teamlogos/nfl/500/bal.png",
    "BUF": "https://a.espncdn.com/i/teamlogos/nfl/500/buf.png",
    "CAR": "https://a.espncdn.com/i/teamlogos/nfl/500/car.png",
    "CHI": "https://a.espncdn.com/i/teamlogos/nfl/500/chi.png",
    "CIN": "https://a.espncdn.com/i/teamlogos/nfl/500/cin.png",
    "CLE": "https://a.espncdn.com/i/teamlogos/nfl/500/cle.png",
    "DAL": "https://a.espncdn.com/i/teamlogos/nfl/500/dal.png",
    "DEN": "https://a.espncdn.com/i/teamlogos/nfl/500/den.png",
    "DET": "https://a.espncdn.com/i/teamlogos/nfl/500/det.png",
    "GB": "https://a.espncdn.com/i/teamlogos/nfl/500/gb.png",
    "HOU": "https://a.espncdn.com/i/teamlogos/nfl/500/hou.png",
    "IND": "https://a.espncdn.com/i/teamlogos/nfl/500/ind.png",
    "JAX": "https://a.espncdn.com/i/teamlogos/nfl/500/jax.png",
    "KC": "https://a.espncdn.com/i/teamlogos/nfl/500/kc.png",
    "LV": "https://a.espncdn.com/i/teamlogos/nfl/500/lv.png",
    "LAC": "https://a.espncdn.com/i/teamlogos/nfl/500/lac.png",
    "LAR": "https://a.espncdn.com/i/teamlogos/nfl/500/lar.png",
    "MIA": "https://a.espncdn.com/i/teamlogos/nfl/500/mia.png",
    "MIN": "https://a.espncdn.com/i/teamlogos/nfl/500/min.png",
    "NE": "https://a.espncdn.com/i/teamlogos/nfl/500/ne.png",
    "NO": "https://a.espncdn.com/i/teamlogos/nfl/500/no.png",
    "NYG": "https://a.espncdn.com/i/teamlogos/nfl/500/nyg.png",
    "NYJ": "https://a.espncdn.com/i/teamlogos/nfl/500/nyj.png",
    "PHI": "https://a.espncdn.com/i/teamlogos/nfl/500/phi.png",
    "PIT": "https://a.espncdn.com/i/teamlogos/nfl/500/pit.png",
    "SEA": "https://a.espncdn.com/i/teamlogos/nfl/500/sea.png",
    "SF": "https://a.espncdn.com/i/teamlogos/nfl/500/sf.png",
    "TB": "https://a.espncdn.com/i/teamlogos/nfl/500/tb.png",
    "TEN": "https://a.espncdn.com/i/teamlogos/nfl/500/ten.png",
    "WAS": "https://a.espncdn.com/i/teamlogos/nfl/500/wsh.png",
}

TEAM_NAMES = {
    "ARI": "Arizona Cardinals",
    "ATL": "Atlanta Falcons",
    "BAL": "Baltimore Ravens",
    "BUF": "Buffalo Bills",
    "CAR": "Carolina Panthers",
    "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals",
    "CLE": "Cleveland Browns",
    "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos",
    "DET": "Detroit Lions",
    "GB": "Green Bay Packers",
    "HOU": "Houston Texans",
    "IND": "Indianapolis Colts",
    "JAX": "Jacksonville Jaguars",
    "KC": "Kansas City Chiefs",
    "LV": "Las Vegas Raiders",
    "LAC": "Los Angeles Chargers",
    "LAR": "Los Angeles Rams",
    "MIA": "Miami Dolphins",
    "MIN": "Minnesota Vikings",
    "NE": "New England Patriots",
    "NO": "New Orleans Saints",
    "NYG": "New York Giants",
    "NYJ": "New York Jets",
    "PHI": "Philadelphia Eagles",
    "PIT": "Pittsburgh Steelers",
    "SEA": "Seattle Seahawks",
    "SF": "San Francisco 49ers",
    "TB": "Tampa Bay Buccaneers",
    "TEN": "Tennessee Titans",
    "WAS": "Washington Commanders",
}

CONTRACT_KEYWORDS = [
    "sign", "signed", "signing", "agreement", "deal", "contract",
    "extension", "extended", "re-sign", "re-signed", "tag", "franchise tag"
]

TRADE_KEYWORDS = [
    "trade", "traded", "acquire", "acquired", "swap", "swapped", "dealt"
]

OTHER_MOVE_KEYWORDS = [
    "release", "released", "waive", "waived", "cut", "cuts",
    "roster", "practice squad", "injured reserve", "ir"
]

COMPLETED_WORDS = ["acquired", "acquire", "traded", "lands", "gets"]
RUMOR_WORDS = ["rumor", "rumours", "report", "talks", "discussing", "expected", "pursuing"]

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

session: aiohttp.ClientSession | None = None

scores_message_id: int | None = None
news_message_id: int | None = None
previous_scores: dict[str, tuple[str, str, str]] = {}

PLAYER_INDEX: list[dict] = []
PLAYER_LOOKUP: dict[str, dict] = {}


def normalize_name(name: str) -> str:
    return " ".join(name.lower().strip().split())


async def fetch_json(url: str) -> dict:
    global session
    if session is None:
        raise RuntimeError("HTTP session not started.")
    async with session.get(url, timeout=25) as resp:
        resp.raise_for_status()
        return await resp.json()


async def fetch_text(url: str) -> str:
    global session
    if session is None:
        raise RuntimeError("HTTP session not started.")
    async with session.get(url, timeout=25, headers={"User-Agent": "Mozilla/5.0"}) as resp:
        resp.raise_for_status()
        return await resp.text()


PLAYOFF_WEEK_LABELS = {
    1: "Wild Card",
    2: "Divisional Round",
    3: "Conference Championship",
    4: "Pro Bowl",
    5: "Super Bowl",
}


def _parse_games(data: dict) -> list[dict]:
    games = []
    for event in data.get("events", []):
        competition = event.get("competitions", [{}])[0]
        competitors = competition.get("competitors", [])

        away = next((c for c in competitors if c.get("homeAway") == "away"), {})
        home = next((c for c in competitors if c.get("homeAway") == "home"), {})

        status = competition.get("status", {})
        status_type = status.get("type", {})
        situation = competition.get("situation", {})

        # Determine winner for finished games
        away_rec = away.get("records", [{}])[0].get("summary", "") if away.get("records") else ""
        home_rec = home.get("records", [{}])[0].get("summary", "") if home.get("records") else ""

        games.append({
            "id": event.get("id"),
            "name": event.get("shortName", event.get("name", "NFL Game")),
            "away_team": away.get("team", {}).get("abbreviation", "AWAY"),
            "away_name": away.get("team", {}).get("displayName", "Away"),
            "home_team": home.get("team", {}).get("abbreviation", "HOME"),
            "home_name": home.get("team", {}).get("displayName", "Home"),
            "away_score": away.get("score", "0"),
            "home_score": home.get("score", "0"),
            "away_winner": away.get("winner", False),
            "home_winner": home.get("winner", False),
            "away_record": away_rec,
            "home_record": home_rec,
            "state": status_type.get("shortDetail", "TBD"),
            "completed": status_type.get("completed", False),
            "in_progress": status_type.get("name", "") == "STATUS_IN_PROGRESS",
            "possession": situation.get("possession"),
            "down_distance": situation.get("downDistanceText", ""),
        })
    return games


async def get_scoreboard_data(
    week: int | None = None,
    season_type: int | None = None,
    year: int | None = None,
) -> tuple[list[dict], dict]:
    """
    Fetch NFL scores for a given week/season.
    Returns (games, meta) where meta contains season context.
    season_type: 1=preseason, 2=regular, 3=postseason
    """
    params = []
    if year is not None:
        params.append(f"year={year}")
    if season_type is not None:
        params.append(f"seasontype={season_type}")
    if week is not None:
        params.append(f"week={week}")

    url = ESPN_SCOREBOARD_URL + ("?" + "&".join(params) if params else "")
    data = await fetch_json(url)

    season = data.get("season", {})
    week_data = data.get("week", {})

    actual_type = season.get("type", season_type or 2)
    actual_year = season.get("year", year or datetime.now().year)
    actual_week = week_data.get("number", week or 1)

    if actual_type == 1:
        type_name = "Preseason"
        max_week = 4
    elif actual_type == 3:
        type_name = "Playoffs"
        max_week = 5
    else:
        type_name = "Regular Season"
        max_week = 18

    if actual_type == 3:
        week_label = PLAYOFF_WEEK_LABELS.get(actual_week, f"Playoff Week {actual_week}")
    else:
        week_label = f"Week {actual_week}"

    meta = {
        "year": actual_year,
        "season_type": actual_type,
        "type_name": type_name,
        "week": actual_week,
        "week_label": week_label,
        "max_week": max_week,
        "display": f"{type_name} • {week_label} • {actual_year - 1}/{actual_year}",
    }

    return _parse_games(data), meta


async def get_live_scoreboard() -> list[dict]:
    """Kept for the auto-post loop — fetches current week only."""
    games, _ = await get_scoreboard_data()
    return games


async def get_game_summary(event_id: str) -> dict:
    return await fetch_json(ESPN_SUMMARY_URL.format(event_id=event_id))


async def scrape_basic_headlines(url: str, limit: int = 5) -> list[dict]:
    try:
        text = await fetch_text(url)
        soup = BeautifulSoup(text, "html.parser")
        items = []
        seen = set()

        for a in soup.find_all("a", href=True):
            title = a.get_text(" ", strip=True)
            href = a["href"]

            if not title or len(title) < 20:
                continue

            if href.startswith("/"):
                if "yahoo.com" in url:
                    href = "https://sports.yahoo.com" + href
                elif "nfl.com" in url:
                    href = "https://www.nfl.com" + href

            if not href.startswith("http"):
                continue

            key = (title, href)
            if key in seen:
                continue
            seen.add(key)

            items.append({
                "headline": html.unescape(title),
                "description": "Fallback source headline",
                "url": href
            })

            if len(items) >= limit:
                break

        return items
    except Exception:
        return []


async def get_news_items(limit: int = 5) -> list[dict]:
    try:
        data = await fetch_json(ESPN_NEWS_URL)
        items = []
        for article in data.get("articles", [])[:limit]:
            url = article.get("links", {}).get("web", {}).get("href", "")
            items.append({
                "headline": article.get("headline", "No headline"),
                "description": article.get("description", "No description"),
                "url": url,
                "source": "ESPN"
            })
        if items:
            return items
    except Exception:
        pass

    nfl_items = await scrape_basic_headlines(NFL_NEWS_URL, limit=limit)
    if nfl_items:
        for item in nfl_items:
            item["source"] = "NFL.com"
        return nfl_items

    yahoo_items = await scrape_basic_headlines(YAHOO_NFL_NEWS_URL, limit=limit)
    for item in yahoo_items:
        item["source"] = "Yahoo Sports"
    return yahoo_items


async def get_recent_trade_articles(limit: int = 8) -> list[dict]:
    items = await get_news_items(limit=20)
    trades = []

    for item in items:
        text = f"{item.get('headline', '')} {item.get('description', '')}".lower()
        if any(word in text for word in TRADE_KEYWORDS):
            trades.append(item)
        if len(trades) >= limit:
            break

    return trades


async def get_trade_tracker_sections(limit: int = 12) -> dict:
    items = await get_news_items(limit=30)
    sections = {"completed": [], "rumors": [], "other": []}

    for item in items:
        text = f"{item.get('headline', '')} {item.get('description', '')}".lower()
        if not any(word in text for word in TRADE_KEYWORDS):
            continue

        if any(word in text for word in COMPLETED_WORDS):
            sections["completed"].append(item)
        elif any(word in text for word in RUMOR_WORDS):
            sections["rumors"].append(item)
        else:
            sections["other"].append(item)

        total = len(sections["completed"]) + len(sections["rumors"]) + len(sections["other"])
        if total >= limit:
            break

    return sections


async def get_market_watch_sections(limit: int = 18) -> dict:
    items = await get_news_items(limit=30)

    sections = {
        "trades": [],
        "contracts": [],
        "other": []
    }

    for item in items:
        headline = item.get("headline", "")
        description = item.get("description", "")
        text = f"{headline} {description}".lower()

        entry = {
            "headline": headline,
            "description": description,
            "url": item.get("url", ""),
            "source": item.get("source", "Source")
        }

        if any(word in text for word in TRADE_KEYWORDS):
            sections["trades"].append(entry)
        elif any(word in text for word in CONTRACT_KEYWORDS):
            sections["contracts"].append(entry)
        elif any(word in text for word in OTHER_MOVE_KEYWORDS):
            sections["other"].append(entry)

        total = len(sections["trades"]) + len(sections["contracts"]) + len(sections["other"])
        if total >= limit:
            break

    return sections


async def _fetch_team_roster(team_abbr: str) -> list[dict]:
    slug = ROSTER_SLUGS.get(team_abbr, team_abbr.lower())
    url = ESPN_TEAM_ROSTER_URL.format(team=slug)
    try:
        data = await fetch_json(url)
    except Exception:
        return []

    team_logo = TEAM_LOGOS.get(team_abbr, "")
    players = []

    for group in data.get("athletes", []):
        for item in group.get("items", []):
            athlete_id = str(item.get("id", ""))
            display_name = item.get("displayName") or item.get("fullName")
            if not athlete_id or not display_name:
                continue

            position = item.get("position", {}).get("abbreviation", "UNK")
            jersey = item.get("jersey", "")
            headshot = f"https://a.espncdn.com/i/headshots/nfl/players/full/{athlete_id}.png"

            players.append({
                "id": athlete_id,
                "name": display_name,
                "position": position,
                "team": team_abbr,
                "jersey": jersey,
                "headshot": headshot,
                "team_logo": team_logo,
                "search": normalize_name(display_name),
                "label": f"{display_name} ({team_abbr}, {position})",
            })

    return players


async def build_player_index() -> None:
    global PLAYER_INDEX, PLAYER_LOOKUP

    import asyncio
    tasks = [_fetch_team_roster(abbr) for abbr in TEAM_NAMES]
    results = await asyncio.gather(*tasks)

    fresh_index = []
    fresh_lookup = {}
    seen_ids: set[str] = set()

    for roster in results:
        for player in roster:
            pid = player["id"]
            if pid in seen_ids:
                continue
            seen_ids.add(pid)
            fresh_index.append(player)
            fresh_lookup[pid] = player

    PLAYER_INDEX = fresh_index
    PLAYER_LOOKUP = fresh_lookup


def search_players(query: str, limit: int = 25) -> list[dict]:
    q = normalize_name(query)
    if not q:
        return PLAYER_INDEX[:limit]

    starts = [p for p in PLAYER_INDEX if p["search"].startswith(q)]
    contains = [p for p in PLAYER_INDEX if q in p["search"] and not p["search"].startswith(q)]
    return (starts + contains)[:limit]


def resolve_player_by_name(query: str) -> dict | None:
    matches = search_players(query, limit=10)
    if not matches:
        return None

    q = normalize_name(query)
    exact = next((p for p in matches if p["search"] == q), None)
    return exact or matches[0]


async def get_player_profile(athlete_id: str) -> dict:
    try:
        return await fetch_json(ESPN_ATHLETE_PROFILE_URL.format(athlete_id=athlete_id))
    except Exception:
        return {}


async def get_player_gamelog(athlete_id: str) -> dict:
    try:
        return await fetch_json(ESPN_ATHLETE_GAMELOG_URL.format(athlete_id=athlete_id))
    except Exception:
        return {}


async def get_league_leaders(year: int = 2025, season_type: int = 2) -> dict:
    """Fetch NFL stat leaders from ESPN core API and resolve player names."""
    import asyncio

    url = ESPN_LEADERS_URL.format(year=year, stype=season_type)
    try:
        data = await fetch_json(url)
    except Exception:
        return {"offense": {}, "defense": {}, "year": year}

    all_want = set(_LEADERS_OFFENSE + _LEADERS_DEFENSE)
    cat_data: dict[str, list[dict]] = {}
    needed_ids: set[str] = set()

    for cat in data.get("categories", []):
        cat_name = cat.get("displayName", "")
        if cat_name not in all_want:
            continue
        entries = []
        for leader in cat.get("leaders", [])[:5]:
            ref = leader.get("athlete", {}).get("$ref", "")
            m = re.search(r"/athletes/(\d+)", ref)
            if m:
                aid = m.group(1)
                needed_ids.add(aid)
                entries.append({"id": aid, "value": leader.get("displayValue", "")})
        if entries:
            cat_data[cat_name] = entries

    name_map: dict[str, dict] = {}
    missing_ids = []
    for aid in needed_ids:
        p = PLAYER_LOOKUP.get(aid)
        if p:
            name_map[aid] = {"name": p["name"], "team": p.get("team", "")}
        else:
            missing_ids.append(aid)

    if missing_ids:
        async def _fetch_ath(aid: str):
            ath_url = (
                f"https://sports.core.api.espn.com/v2/sports/football/leagues/nfl"
                f"/seasons/{year}/athletes/{aid}?lang=en&region=us"
            )
            try:
                d = await fetch_json(ath_url)
                short = d.get("shortName") or d.get("displayName") or "Unknown"
                return aid, short
            except Exception:
                return aid, "Unknown"

        resolved = await asyncio.gather(*[_fetch_ath(aid) for aid in missing_ids])
        for aid, name in resolved:
            name_map[aid] = {"name": name, "team": ""}

    offense: dict[str, list] = {}
    defense: dict[str, list] = {}

    for cat_name, entries in cat_data.items():
        players = []
        for e in entries:
            info = name_map.get(e["id"], {})
            players.append({
                "name": info.get("name", "Unknown"),
                "team": info.get("team", ""),
                "value": e["value"],
            })
        if cat_name in _LEADERS_OFFENSE:
            offense[cat_name] = players
        else:
            defense[cat_name] = players

    return {"offense": offense, "defense": defense, "year": year}


def extract_stats_from_profile(profile: dict) -> list[dict]:
    """Pull season stat sections out of the ESPN athlete profile response."""
    stats = []
    for key in ("statistics", "stats", "splits"):
        raw = profile.get(key)
        if isinstance(raw, list) and raw:
            stats = raw
            break
        if isinstance(raw, dict):
            # some endpoints wrap in {splits: {categories: [...]}}
            categories = raw.get("categories") or raw.get("splits") or []
            if isinstance(categories, list) and categories:
                stats = categories
                break
    return stats


def extract_stats_from_gamelog(gamelog: dict) -> list[dict]:
    """Pull per-game stat rows out of the ESPN gamelog response."""
    entries = []
    season_types = gamelog.get("seasonTypes") or []
    for st in season_types:
        categories = st.get("categories") or []
        for cat in categories:
            events = cat.get("events") or []
            for evt in events:
                stat_parts = []
                for s in evt.get("stats", []):
                    if isinstance(s, dict):
                        n = s.get("displayName") or s.get("name")
                        v = s.get("displayValue") or s.get("value")
                        if n and v is not None:
                            stat_parts.append(f"{n}: {v}")
                opponent = evt.get("opponent", {}).get("displayName", "Opponent")
                date = evt.get("atVs", "") + " " + opponent
                entries.append({
                    "title": date.strip(),
                    "value": " • ".join(stat_parts) if stat_parts else "No stats",
                })

    # fallback — original flat events list
    if not entries:
        for event in gamelog.get("events", []):
            if not isinstance(event, dict):
                continue
            opponent = event.get("opponent", {}).get("displayName", "Opponent")
            date = event.get("date", "Game")
            stat_parts = []
            for s in event.get("stats", []):
                if isinstance(s, dict):
                    n = s.get("displayName") or s.get("name")
                    v = s.get("displayValue") or s.get("value")
                    if n and v is not None:
                        stat_parts.append(f"{n}: {v}")
            entries.append({
                "title": f"{date} vs {opponent}",
                "value": " • ".join(stat_parts) if stat_parts else "No stats",
            })

    if not entries:
        entries.append({"title": "Game Log", "value": "No game log data available."})

    return entries


def merge_player_profile(base_player: dict, profile: dict) -> dict:
    """Merge ESPN index data with the athlete profile endpoint response."""
    player = dict(base_player)
    player["profile_source"] = "ESPN athlete index"

    # Always build headshot from ESPN CDN using athlete ID
    if player.get("id"):
        player["headshot"] = f"https://a.espncdn.com/i/headshots/nfl/players/full/{player['id']}.png"

    if not isinstance(profile, dict):
        return player

    # The profile endpoint wraps athlete data under "athlete"
    athlete = profile.get("athlete") or profile
    if isinstance(athlete, dict):
        team_abbr = (athlete.get("team") or {}).get("abbreviation")
        position_abbr = (athlete.get("position") or {}).get("abbreviation")
        jersey = athlete.get("jersey")
        display_name = athlete.get("displayName") or athlete.get("fullName")

        if team_abbr:
            player["team"] = team_abbr
        if position_abbr:
            player["position"] = position_abbr
        if jersey:
            player["jersey"] = jersey
        if display_name:
            player["name"] = display_name

        logos = (athlete.get("team") or {}).get("logos") or []
        if isinstance(logos, list) and logos:
            player["team_logo"] = logos[0].get("href", "")

        player["profile_source"] = "ESPN profile"

    # Attach season stats extracted from the profile
    player["stats"] = extract_stats_from_profile(profile)

    return player


async def fetch_full_player_profile(name: str) -> dict | None:
    """
    Full pipeline:
      1. Search player name → get athlete ID from local index
      2. Call ESPN athlete profile endpoint
      3. Call ESPN gamelog endpoint  (concurrent with step 2)
      4. Merge profile data + stats data into one unified dict
    Returns None if the player cannot be found.
    """
    import asyncio

    # Step 1 — search name, resolve athlete ID
    base_player = resolve_player_by_name(name)
    if base_player is None:
        return None

    athlete_id = base_player["id"]

    # Steps 2 & 3 — fetch profile and gamelog concurrently
    profile_data, gamelog_data = await asyncio.gather(
        get_player_profile(athlete_id),
        get_player_gamelog(athlete_id),
    )

    # Step 4 — merge profile data + stats data
    merged = merge_player_profile(base_player, profile_data)
    merged["_gamelog_entries"] = extract_stats_from_gamelog(gamelog_data)
    merged["_raw_profile"] = profile_data
    merged["_raw_gamelog"] = gamelog_data

    return merged


def build_scoreboard_embed(games: list[dict], meta: dict | None = None) -> discord.Embed:
    if meta:
        title = f"🏈 NFL Scoreboard — {meta['week_label']}"
        description = f"**{meta['type_name']} • {meta['year'] - 1}/{meta['year']} Season**\nUpdated {datetime.now().strftime('%b %d, %Y • %I:%M %p')}"
    else:
        title = "🏈 NFL Scoreboard"
        description = f"Updated {datetime.now().strftime('%b %d, %Y • %I:%M %p')}"

    embed = discord.Embed(title=title, description=description, color=0x7A5C2E)

    if not games:
        embed.add_field(
            name="No Games Found",
            value="No games found for this week. Use the buttons to browse other weeks.",
            inline=False,
        )
        return embed

    any_live = any(g.get("in_progress") for g in games)

    for game in games[:16]:
        away = game["away_team"]
        home = game["home_team"]
        a_score = game["away_score"]
        h_score = game["home_score"]
        state = game["state"]

        # Bold the winning team's score when the game is final
        if game.get("completed"):
            if game.get("away_winner"):
                score_line = f"**{away} {a_score}** — {home} {h_score}"
            elif game.get("home_winner"):
                score_line = f"{away} {a_score} — **{home} {h_score}**"
            else:
                score_line = f"{away} {a_score} — {home} {h_score}"
        else:
            score_line = f"{away} {a_score} — {home} {h_score}"

        extra = f"\n{state}"
        if game.get("in_progress"):
            if game.get("down_distance"):
                extra += f"  •  {game['down_distance']}"

        rec_away = f" ({game['away_record']})" if game.get("away_record") else ""
        rec_home = f" ({game['home_record']})" if game.get("home_record") else ""
        field_name = f"{away}{rec_away} @ {home}{rec_home}"

        embed.add_field(name=field_name[:256], value=(score_line + extra)[:1024], inline=False)

    if any_live:
        embed.set_footer(text="🔴 LIVE • USO NFL Bot")
    else:
        embed.set_footer(text="USO NFL Bot")

    return embed


def build_news_embed(items: list[dict]) -> discord.Embed:
    embed = discord.Embed(
        title="📰 NFL Headlines",
        description="Latest NFL headlines",
        color=0x7A5C2E,
    )

    if not items:
        embed.add_field(name="No News", value="No headlines available.", inline=False)
        return embed

    for item in items[:6]:
        source = item.get("source", "Source")
        link = f"[Read Article]({item['url']})" if item.get("url") else ""
        desc = item.get("description", "")[:180]
        value = f"{desc}\n{link}\n**Source:** {source}" if link else f"{desc}\n**Source:** {source}"
        embed.add_field(name=item.get("headline", "Headline")[:256], value=value[:1024], inline=False)

    return embed


def build_recent_trades_embed(items: list[dict]) -> discord.Embed:
    embed = discord.Embed(
        title="🔥 NFL OFFSEASON TRADE TRACKER",
        description="Recent trade-related headlines",
        color=0x7A5C2E
    )

    if not items:
        embed.add_field(
            name="No recent trade headlines found",
            value="No trade-related headlines were returned right now.",
            inline=False
        )
        return embed

    for item in items[:6]:
        source = item.get("source", "Source")
        link = f"[Read Article]({item['url']})" if item.get("url") else ""
        desc = item.get("description", "No summary available.")[:220]
        text = f"{desc}\n{link}\n**Source:** {source}" if link else f"{desc}\n**Source:** {source}"
        embed.add_field(name=item.get("headline", "Headline")[:256], value=text[:1024], inline=False)

    embed.set_footer(text="USO NFL Bot • Trade/news tracker")
    return embed


def build_trade_tracker_embed(sections: dict) -> discord.Embed:
    embed = discord.Embed(
        title="📊 NFL TRADE TRACKER",
        description="Recent trade-related headlines",
        color=0x7A5C2E
    )

    def block(items, empty_text="None right now."):
        if not items:
            return empty_text
        lines = []
        for item in items[:3]:
            source = item.get("source", "")
            link = f" — [Read]({item['url']})" if item.get("url") else ""
            lines.append(f"• **{item.get('headline','Headline')}**{link} ({source})")
        return "\n".join(lines)

    embed.add_field(name="Completed / Strong Signals", value=block(sections["completed"]), inline=False)
    embed.add_field(name="Rumors / Reports", value=block(sections["rumors"]), inline=False)
    embed.add_field(name="Other Trade Headlines", value=block(sections["other"]), inline=False)
    embed.set_footer(text="USO NFL Bot")
    return embed


def build_market_watch_embed(sections: dict) -> discord.Embed:
    embed = discord.Embed(
        title="📊 NFL MARKET WATCH",
        description="Latest trades and contract headlines",
        color=0x7A5C2E,
    )

    def format_block(items, empty_text="None right now."):
        if not items:
            return empty_text
        lines = []
        for item in items[:5]:
            source = item.get("source", "Source")
            link = f" — [Read]({item['url']})" if item.get("url") else ""
            lines.append(f"• **{item['headline']}**{link} ({source})")
        return "\n".join(lines)

    embed.add_field(name="🔁 Trades", value=format_block(sections["trades"]), inline=False)
    embed.add_field(name="💰 Contracts", value=format_block(sections["contracts"]), inline=False)
    embed.add_field(name="📝 Other Moves", value=format_block(sections["other"]), inline=False)
    embed.set_footer(text="USO NFL Bot • Live market watch")
    return embed


def build_leaders_embed(data: dict, mode: str) -> discord.Embed:
    year = data.get("year", 2025)
    if mode == "offense":
        title = f"🏈 NFL Offensive Leaders — {year}"
        cat_order = _LEADERS_OFFENSE
        groups = data.get("offense", {})
    else:
        title = f"🛡️ NFL Defensive Leaders — {year}"
        cat_order = _LEADERS_DEFENSE
        groups = data.get("defense", {})

    embed = discord.Embed(title=title, color=0x7A5C2E)

    for cat in cat_order:
        players = groups.get(cat, [])
        if not players:
            continue
        lines = []
        for i, p in enumerate(players, 1):
            team_str = f" ({p['team']})" if p.get("team") else ""
            lines.append(f"{i}. **{p['name']}**{team_str} — {p['value']}")
        embed.add_field(name=cat, value="\n".join(lines), inline=True)

    if not any(groups.get(c) for c in cat_order):
        embed.description = "No stats available right now."

    embed.set_footer(text="USO NFL Bot • ESPN")
    return embed


class LeagueLeadersView(discord.ui.View):
    def __init__(self, data: dict):
        super().__init__(timeout=180)
        self.data = data
        self.mode = "offense"

    def build_embed(self) -> discord.Embed:
        return build_leaders_embed(self.data, self.mode)

    @discord.ui.button(label="🏈 Offense", style=discord.ButtonStyle.primary, row=0)
    async def offense_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mode = "offense"
        self.offense_btn.style = discord.ButtonStyle.primary
        self.defense_btn.style = discord.ButtonStyle.secondary
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="🛡️ Defense", style=discord.ButtonStyle.secondary, row=0)
    async def defense_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mode = "defense"
        self.offense_btn.style = discord.ButtonStyle.secondary
        self.defense_btn.style = discord.ButtonStyle.primary
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


def build_game_stats_embed(game_name: str, summary: dict) -> discord.Embed:
    embed = discord.Embed(
        title=f"📊 {game_name}",
        color=0x7A5C2E,
    )

    leaders = summary.get("leaders", [])
    if not leaders:
        embed.description = "No leader stats available yet."
        return embed

    for group in leaders[:4]:
        leader_list = group.get("leaders", [])
        if not leader_list:
            continue
        leader = leader_list[0]
        athlete = leader.get("athlete", {}).get("displayName", "Unknown")
        display_value = leader.get("displayValue", "No stats")
        name = group.get("name", "Leaders")
        embed.add_field(name=name, value=f"**{athlete}** — {display_value}", inline=False)

    return embed


def build_player_stats_embed(player: dict) -> discord.Embed:
    team_display = TEAM_NAMES.get(player.get("team", ""), player.get("team", "N/A"))

    embed = discord.Embed(
        title=f"👤 {player['name']}",
        description=(
            f"**Team:** {team_display}\n"
            f"**Position:** {player.get('position', 'N/A')}\n"
            f"**Jersey:** {player.get('jersey') or 'N/A'}"
        ),
        color=0x7A5C2E,
    )

    if player.get("headshot"):
        embed.set_thumbnail(url=player["headshot"])
    elif TEAM_LOGOS.get(player.get("team", "")):
        embed.set_thumbnail(url=TEAM_LOGOS[player["team"]])

    source_label = player.get("profile_source", "ESPN")
    if player.get("team_logo"):
        embed.set_footer(text=f"USO NFL Bot • {source_label}", icon_url=player["team_logo"])
    else:
        embed.set_footer(text=f"USO NFL Bot • {source_label}")

    # Stats come merged into player["stats"] by fetch_full_player_profile
    statistics = player.get("stats") or []
    added = 0

    for section in statistics[:8]:
        label = section.get("displayName") or section.get("name") or "Stats"
        stats = section.get("stats", [])
        lines = []

        for stat in stats[:6]:
            if isinstance(stat, dict):
                stat_name = stat.get("displayName") or stat.get("name")
                stat_value = stat.get("displayValue") or stat.get("value")
                if stat_name and stat_value is not None:
                    lines.append(f"**{stat_name}:** {stat_value}")

        if lines:
            embed.add_field(name=label[:256], value="\n".join(lines)[:1024], inline=False)
            added += 1

        if added >= 4:
            break

    if added == 0:
        embed.add_field(name="Stats", value="Stats unavailable right now.", inline=False)

    return embed


class PlayerStatsView(discord.ui.View):
    """Prev / Next season navigation for /playerstats."""

    def __init__(self, player: dict, season_blocks: list[dict]):
        super().__init__(timeout=180)
        self.player = player
        self.season_blocks = season_blocks
        self.page = 0
        self._sync_buttons()

    def _sync_buttons(self):
        self.prev_button.disabled = self.page == 0
        self.next_button.disabled = self.page >= len(self.season_blocks) - 1

    def build_embed(self) -> discord.Embed:
        return build_season_stats_embed(
            self.player,
            self.season_blocks[self.page],
            self.page,
            len(self.season_blocks),
        )

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


class GameLogView(discord.ui.View):
    def __init__(self, player: dict, entries: list[dict]):
        super().__init__(timeout=180)
        self.player = player
        self.entries = entries
        self.page = 0

    def build_embed(self) -> discord.Embed:
        current = self.entries[self.page]
        team_display = TEAM_NAMES.get(self.player["team"], self.player["team"])

        embed = discord.Embed(
            title=f"📋 {self.player['name']} Game Log",
            description=(
                f"**Team:** {team_display}\n"
                f"**Position:** {self.player['position']}\n"
                f"**Jersey:** {self.player['jersey'] if self.player['jersey'] else 'N/A'}"
            ),
            color=0x7A5C2E,
        )

        if self.player.get("headshot"):
            embed.set_thumbnail(url=self.player["headshot"])
        elif TEAM_LOGOS.get(self.player["team"]):
            embed.set_thumbnail(url=TEAM_LOGOS[self.player["team"]])

        source_label = self.player.get("profile_source", "Source unavailable")
        embed.add_field(name=current["title"][:256], value=current["value"][:1024], inline=False)
        embed.set_footer(text=f"Game {self.page + 1}/{len(self.entries)} • Profile source: {source_label}")
        return embed

    @discord.ui.button(label="Prev", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page < len(self.entries) - 1:
            self.page += 1
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


def extract_season_stat_blocks(gamelog: dict) -> list[dict]:
    """Build season stat blocks from the raw ESPN gamelog response."""
    seasons = []

    if not isinstance(gamelog, dict):
        return seasons

    col_headers = gamelog.get("displayNames") or gamelog.get("labels") or []

    for season_type in gamelog.get("seasonTypes", []):
        season_label = season_type.get("displayName", "Season")
        sections = []

        for category in season_type.get("categories", []):
            cat_name = category.get("displayName", "Stats")
            totals = category.get("totals", [])

            if not totals:
                continue

            lines = []
            for i, val in enumerate(totals):
                if i < len(col_headers) and str(val).strip():
                    lines.append(f"{col_headers[i]}: {val}")

            if lines:
                sections.append({"title": cat_name, "lines": lines[:20]})

        if sections:
            seasons.append({"label": season_label, "sections": sections})

    return seasons


def build_season_stats_embed(player: dict, season_block: dict, page: int, total: int) -> discord.Embed:
    team_display = TEAM_NAMES.get(player["team"], player["team"])

    embed = discord.Embed(
        title=f"📊 {season_block['label']} Stats — {player['name']}",
        description=(
            f"**POS:** {player['position']}   "
            f"**TEAM:** {team_display}   "
            f"**JERSEY:** {player['jersey'] if player.get('jersey') else 'N/A'}"
        ),
        color=0x7A5C2E,
    )

    if player.get("headshot"):
        embed.set_thumbnail(url=player["headshot"])
    elif TEAM_LOGOS.get(player.get("team", "")):
        embed.set_thumbnail(url=TEAM_LOGOS[player["team"]])

    for section in season_block["sections"][:4]:
        value = "\n".join(section["lines"][:12]) if section["lines"] else "No stats"
        embed.add_field(name=section["title"][:256], value=value[:1024], inline=False)

    embed.set_footer(text=f"Season {page + 1}/{total} • USO NFL Bot")
    return embed


class SeasonStatsView(discord.ui.View):
    def __init__(self, player: dict, season_blocks: list[dict], gamelog_entries: list[dict]):
        super().__init__(timeout=180)
        self.player = player
        self.season_blocks = season_blocks
        self.gamelog_entries = gamelog_entries
        self.page = 0
        self.mode = "season"
        self.refresh_buttons()

    def refresh_buttons(self):
        self.clear_items()

        for idx, block in enumerate(self.season_blocks[:4]):
            style = discord.ButtonStyle.primary if idx == self.page and self.mode == "season" else discord.ButtonStyle.secondary
            button = discord.ui.Button(label=block["label"][:20], style=style)

            async def season_callback(interaction: discord.Interaction, i=idx):
                self.page = i
                self.mode = "season"
                self.refresh_buttons()
                await interaction.response.edit_message(embed=self.build_embed(), view=self)

            button.callback = season_callback
            self.add_item(button)

        game_log_button = discord.ui.Button(
            label=f"{self.season_blocks[self.page]['label'][:18]} Game Log",
            style=discord.ButtonStyle.secondary if self.mode == "season" else discord.ButtonStyle.primary,
        )

        async def gamelog_callback(interaction: discord.Interaction):
            self.mode = "gamelog"
            self.refresh_buttons()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)

        game_log_button.callback = gamelog_callback
        self.add_item(game_log_button)

    def build_embed(self) -> discord.Embed:
        if self.mode == "season":
            return build_season_stats_embed(
                self.player,
                self.season_blocks[self.page],
                self.page,
                len(self.season_blocks),
            )

        team_display = TEAM_NAMES.get(self.player["team"], self.player["team"])
        embed = discord.Embed(
            title=f"📋 {self.season_blocks[self.page]['label']} Game Log — {self.player['name']}",
            description=(
                f"**Team:** {team_display}\n"
                f"**Position:** {self.player['position']}\n"
                f"**Jersey:** {self.player['jersey'] if self.player.get('jersey') else 'N/A'}"
            ),
            color=0x7A5C2E,
        )

        if self.player.get("headshot"):
            embed.set_thumbnail(url=self.player["headshot"])
        elif TEAM_LOGOS.get(self.player.get("team", "")):
            embed.set_thumbnail(url=TEAM_LOGOS[self.player["team"]])

        if self.gamelog_entries:
            for entry in self.gamelog_entries[:8]:
                embed.add_field(name=entry["title"][:256], value=entry["value"][:1024], inline=False)
        else:
            embed.add_field(name="No Data", value="No game log entries available.", inline=False)

        embed.set_footer(text="USO NFL Bot")
        return embed


class ScoreboardView(discord.ui.View):
    """Week-by-week scoreboard with Prev/Next and Regular Season/Playoffs toggles."""

    def __init__(self, games: list[dict], meta: dict):
        super().__init__(timeout=300)
        self.games = games
        self.meta = meta
        self._sync_buttons()

    def _sync_buttons(self):
        self.prev_button.disabled = self.meta["week"] <= 1
        self.next_button.disabled = self.meta["week"] >= self.meta["max_week"]
        self.reg_button.style = (
            discord.ButtonStyle.primary if self.meta["season_type"] == 2
            else discord.ButtonStyle.secondary
        )
        self.playoff_button.style = (
            discord.ButtonStyle.primary if self.meta["season_type"] == 3
            else discord.ButtonStyle.secondary
        )

    def build_embed(self) -> discord.Embed:
        return build_scoreboard_embed(self.games, self.meta)

    async def _fetch_and_update(self, interaction: discord.Interaction):
        self.games, self.meta = await get_scoreboard_data(
            week=self.meta["week"],
            season_type=self.meta["season_type"],
            year=self.meta["year"],
        )
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="◀ Prev Week", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.meta["week"] -= 1
        await self._fetch_and_update(interaction)

    @discord.ui.button(label="Next Week ▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.meta["week"] += 1
        await self._fetch_and_update(interaction)

    @discord.ui.button(label="Regular Season", style=discord.ButtonStyle.primary, row=1)
    async def reg_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.meta["season_type"] = 2
        self.meta["week"] = 18
        self.meta["max_week"] = 18
        await self._fetch_and_update(interaction)

    @discord.ui.button(label="Playoffs", style=discord.ButtonStyle.secondary, row=1)
    async def playoff_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.meta["season_type"] = 3
        self.meta["week"] = 5
        self.meta["max_week"] = 5
        await self._fetch_and_update(interaction)


async def player_name_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> list[app_commands.Choice[str]]:
    matches = search_players(current, limit=25)
    return [app_commands.Choice(name=p["label"][:100], value=p["name"]) for p in matches]


async def upsert_message(channel_id: int, message_id: int | None, embed: discord.Embed) -> int | None:
    if not channel_id:
        return message_id

    channel = bot.get_channel(channel_id)
    if channel is None:
        return message_id

    if message_id:
        try:
            msg = await channel.fetch_message(message_id)
            await msg.edit(embed=embed)
            return msg.id
        except discord.NotFound:
            pass

    msg = await channel.send(embed=embed)
    return msg.id


@tasks.loop(seconds=45)
async def scores_loop():
    global scores_message_id, previous_scores

    games = await get_live_scoreboard()
    scores_message_id = await upsert_message(
        SCORES_CHANNEL_ID,
        scores_message_id,
        build_scoreboard_embed(games),
    )

    if not ALERTS_CHANNEL_ID:
        return

    alerts_channel = bot.get_channel(ALERTS_CHANNEL_ID)
    if alerts_channel is None:
        return

    for game in games:
        key = game["id"]
        current = (game["away_score"], game["home_score"], game["state"])
        old = previous_scores.get(key)

        if old and old[:2] != current[:2]:
            await alerts_channel.send(
                f"🚨 Score Update: {game['away_team']} {game['away_score']} - "
                f"{game['home_team']} {game['home_score']} ({game['state']})"
            )

        if old and old[2] != current[2] and "Final" in game["state"]:
            await alerts_channel.send(
                f"✅ Final: {game['away_team']} {game['away_score']} - "
                f"{game['home_team']} {game['home_score']}"
            )

        previous_scores[key] = current


@tasks.loop(minutes=10)
async def news_loop():
    global news_message_id
    items = await get_news_items()
    news_message_id = await upsert_message(
        NEWS_CHANNEL_ID,
        news_message_id,
        build_news_embed(items),
    )


_EASTERN = ZoneInfo("America/New_York")

@tasks.loop(time=[
    dtime(8, 0, tzinfo=_EASTERN),
    dtime(17, 0, tzinfo=_EASTERN),
])
async def nflwatch_loop():
    if not NFLWATCH_CHANNEL_ID:
        return
    channel = bot.get_channel(NFLWATCH_CHANNEL_ID)
    if channel is None:
        return
    sections = await get_market_watch_sections()
    embed = build_market_watch_embed(sections)
    now_et = datetime.now(_EASTERN)
    embed.set_footer(text=f"USO NFL Bot • Auto-posted {now_et.strftime('%I:%M %p ET • %b %d, %Y')}")
    await channel.send(embed=embed)


@bot.tree.command(name="scoreboard", description="Show NFL scores — browse past weeks, current week, and live games")
async def scoreboard(interaction: discord.Interaction):
    await interaction.response.defer()
    games, meta = await get_scoreboard_data()
    view = ScoreboardView(games, meta)
    await interaction.followup.send(embed=view.build_embed(), view=view)


@bot.tree.command(name="gamestats", description="Show stat leaders for a live game")
@app_commands.describe(team="Team abbreviation like KC, DAL, SF, BUF")
async def gamestats(interaction: discord.Interaction, team: str):
    await interaction.response.defer()
    team = team.upper().strip()

    games = await get_live_scoreboard()
    target = next((g for g in games if team in (g["away_team"], g["home_team"])), None)

    if target is None:
        await interaction.followup.send(f"No live or listed game found for `{team}`.")
        return

    summary = await get_game_summary(target["id"])
    await interaction.followup.send(embed=build_game_stats_embed(target["name"], summary))


@bot.tree.command(name="playerstats", description="Search a player by name and show stats")
@app_commands.describe(name="Start typing a player name")
@app_commands.autocomplete(name=player_name_autocomplete)
async def playerstats(interaction: discord.Interaction, name: str):
    await interaction.response.defer()

    profile = await fetch_full_player_profile(name)
    if profile is None:
        await interaction.followup.send(f"No player found for `{name}`.")
        return

    season_blocks = extract_season_stat_blocks(profile.get("_raw_gamelog") or {})
    if len(season_blocks) > 1:
        view = PlayerStatsView(profile, season_blocks)
        await interaction.followup.send(embed=view.build_embed(), view=view)
    else:
        await interaction.followup.send(embed=build_player_stats_embed(profile))


@bot.tree.command(name="gamelog", description="Search a player by name and show game log")
@app_commands.describe(name="Start typing a player name")
@app_commands.autocomplete(name=player_name_autocomplete)
async def gamelog(interaction: discord.Interaction, name: str):
    await interaction.response.defer()

    profile = await fetch_full_player_profile(name)
    if profile is None:
        await interaction.followup.send(f"No player found for `{name}`.")
        return

    entries = profile["_gamelog_entries"]
    view = GameLogView(profile, entries)
    await interaction.followup.send(embed=view.build_embed(), view=view)


@bot.tree.command(name="seasonstats", description="Show a player's season stats with year buttons and game log toggle")
@app_commands.describe(name="Start typing a player name")
@app_commands.autocomplete(name=player_name_autocomplete)
async def seasonstats(interaction: discord.Interaction, name: str):
    await interaction.response.defer()

    profile = await fetch_full_player_profile(name)
    if profile is None:
        await interaction.followup.send(f"No player found for `{name}`.")
        return

    season_blocks = extract_season_stat_blocks(profile.get("_raw_gamelog") or {})
    if not season_blocks:
        await interaction.followup.send(
            f"No season stats available for **{profile['name']}**. Try `/playerstats` instead."
        )
        return

    view = SeasonStatsView(profile, season_blocks, profile["_gamelog_entries"])
    await interaction.followup.send(embed=view.build_embed(), view=view)


@bot.tree.command(name="headlines", description="Show latest NFL headlines")
async def headlines(interaction: discord.Interaction):
    await interaction.response.defer()
    items = await get_news_items()
    await interaction.followup.send(embed=build_news_embed(items))


@bot.tree.command(name="recenttrades", description="Show recent NFL trade headlines")
async def recenttrades(interaction: discord.Interaction):
    await interaction.response.defer()
    items = await get_recent_trade_articles()
    await interaction.followup.send(embed=build_recent_trades_embed(items))


@bot.tree.command(name="tradetracker", description="Show categorized NFL trade headlines")
async def tradetracker(interaction: discord.Interaction):
    await interaction.response.defer()
    sections = await get_trade_tracker_sections()
    await interaction.followup.send(embed=build_trade_tracker_embed(sections))


@bot.tree.command(name="nflwatch", description="Show current NFL trades, contracts, and roster moves")
async def nflwatch(interaction: discord.Interaction):
    await interaction.response.defer()
    sections = await get_market_watch_sections()
    embed = build_market_watch_embed(sections)
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="leagueleaders", description="Show NFL stat leaders for offense and defense")
async def leagueleaders(interaction: discord.Interaction):
    await interaction.response.defer()
    data = await get_league_leaders()
    view = LeagueLeadersView(data)
    await interaction.followup.send(embed=view.build_embed(), view=view)


@bot.event
async def on_ready():
    global session

    if session is None:
        session = aiohttp.ClientSession()

    if not PLAYER_INDEX:
        try:
            await build_player_index()
            print(f"Loaded {len(PLAYER_INDEX)} players.")
        except Exception as e:
            print(f"Could not load player index: {e}")

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands.")
    except Exception as e:
        print(f"Command sync error: {e}")

    if not scores_loop.is_running():
        scores_loop.start()

    if not news_loop.is_running():
        news_loop.start()

    if not nflwatch_loop.is_running():
        nflwatch_loop.start()

    print(f"BOT READY - Logged in as {bot.user}")


async def shutdown_session():
    global session
    if session and not session.closed:
        await session.close()


if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing. Add it in Replit Secrets.")

try:
    bot.run(TOKEN)
finally:
    import asyncio
    asyncio.run(shutdown_session())
