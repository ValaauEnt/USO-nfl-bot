import os
import re
import html
import asyncio
import xml.etree.ElementTree as ET
import aiohttp
from aiohttp import web as aiohttp_web
import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, time as dtime, timezone, timedelta
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from typing import Optional

TOKEN = os.getenv("DISCORD_TOKEN")

# Optional auto-post channels. Set to your Discord channel ID to enable.
SCORES_CHANNEL_ID = 0
NEWS_CHANNEL_ID = 0          # updated at runtime via /set-news-channel
ALERTS_CHANNEL_ID = 0
NFLWATCH_CHANNEL_ID = 1480936006395101387  # Auto-posts NFL market watch at 8am and 5pm ET daily

# ESPN
ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
ESPN_NEWS_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news"
ESPN_SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={event_id}"
ESPN_TEAM_ROSTER_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{team}/roster"
ESPN_TEAM_SCHEDULE_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{team}/schedule"

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

# RSS feeds — pulled simultaneously alongside ESPN
PFT_RSS_URL   = "https://profootballtalk.nbcsports.com/feed/"
YAHOO_RSS_URL = "https://sports.yahoo.com/rss/nfl"

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

# Breaking news tracking
seen_article_ids: set[str] = set()
_news_initialized: bool = False

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


def _parse_espn_article(article: dict) -> dict:
    """Extract a standardised news item dict from a raw ESPN article object."""
    url = article.get("links", {}).get("web", {}).get("href", "")

    # Pick best image: prefer non-motion (real photo) header image
    image_url = ""
    for img in article.get("images", []):
        candidate = img.get("url", "")
        if candidate and "/motion/" not in candidate:
            image_url = candidate
            break
    if not image_url:
        for img in article.get("images", []):
            candidate = img.get("url", "")
            if candidate:
                image_url = candidate
                break

    # Video: grab first clip link if present
    video_url = ""
    for vid in article.get("video", []):
        links = vid.get("links", {})
        clip = (
            links.get("source", {}).get("HD", {}).get("href")
            or links.get("source", {}).get("full", {}).get("href")
            or links.get("web", {}).get("href")
        )
        if clip:
            video_url = clip
            break

    # Parse published timestamp
    published_str = article.get("published", "")
    published_dt: datetime | None = None
    if published_str:
        try:
            published_dt = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
        except ValueError:
            pass

    return {
        "article_id": str(article.get("id", "")),
        "headline": article.get("headline", "No headline"),
        "description": article.get("description", "No description"),
        "url": url,
        "image_url": image_url,
        "video_url": video_url,
        "published": published_dt,
        "source": "ESPN",
    }


async def _fetch_rss_articles(rss_url: str, source_name: str, hours: int = 24) -> list[dict]:
    """Fetch and parse an RSS feed, returning standardised news-item dicts."""
    try:
        text = await fetch_text(rss_url)
        root = ET.fromstring(text)
        channel = root.find("channel")
        if channel is None:
            channel = root  # Atom / bare feeds

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        items: list[dict] = []

        for entry in channel.findall("item"):
            title_el   = entry.find("title")
            link_el    = entry.find("link")
            desc_el    = entry.find("description")
            pubdate_el = entry.find("pubDate")
            # media:content or enclosure for thumbnail
            image_url  = ""
            media_content = entry.find("{http://search.yahoo.com/mrss/}content")
            if media_content is not None:
                image_url = media_content.get("url", "")
            if not image_url:
                enclosure = entry.find("enclosure")
                if enclosure is not None and "image" in enclosure.get("type", ""):
                    image_url = enclosure.get("url", "")

            headline = html.unescape(title_el.text.strip()) if title_el is not None and title_el.text else ""
            if not headline:
                continue

            url = (link_el.text or "").strip() if link_el is not None else ""

            desc_raw = (desc_el.text or "") if desc_el is not None else ""
            # Strip any HTML tags from description
            desc = BeautifulSoup(desc_raw, "html.parser").get_text(" ", strip=True)[:300]

            published_dt: datetime | None = None
            if pubdate_el is not None and pubdate_el.text:
                try:
                    from email.utils import parsedate_to_datetime
                    published_dt = parsedate_to_datetime(pubdate_el.text.strip())
                except Exception:
                    pass

            if published_dt is not None and published_dt < cutoff:
                continue

            # Unique ID: use URL as the stable key
            article_id = re.sub(r"[^a-zA-Z0-9]", "", url)[-80:] or headline[:80]

            items.append({
                "article_id": article_id,
                "headline":   headline,
                "description": desc,
                "url":        url,
                "image_url":  image_url,
                "video_url":  "",
                "published":  published_dt,
                "source":     source_name,
            })

        return items
    except Exception:
        return []


async def get_news_items(limit: int = 5) -> list[dict]:
    try:
        data = await fetch_json(f"{ESPN_NEWS_URL}?limit=50")
        items = [_parse_espn_article(a) for a in data.get("articles", [])[:limit]]
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


async def _fetch_espn_articles(hours: int = 24) -> list[dict]:
    """Fetch ESPN articles from the last `hours` hours."""
    try:
        data = await fetch_json(f"{ESPN_NEWS_URL}?limit=50")
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        items = []
        for article in data.get("articles", []):
            item = _parse_espn_article(article)
            if item["published"] is None or item["published"] >= cutoff:
                items.append(item)
        return items
    except Exception:
        return []


async def get_all_recent_news(hours: int = 24) -> list[dict]:
    """Fetch from ESPN, Pro Football Talk, and Yahoo Sports simultaneously.
    Returns a merged, deduplicated list sorted newest-first."""
    espn_task   = _fetch_espn_articles(hours=hours)
    pft_task    = _fetch_rss_articles(PFT_RSS_URL,   "Pro Football Talk", hours=hours)
    yahoo_task  = _fetch_rss_articles(YAHOO_RSS_URL, "Yahoo Sports",      hours=hours)

    espn_items, pft_items, yahoo_items = await asyncio.gather(
        espn_task, pft_task, yahoo_task
    )

    # Merge all sources — deduplicate by article_id
    seen_ids: set[str] = set()
    merged: list[dict] = []
    for item in espn_items + pft_items + yahoo_items:
        aid = item["article_id"]
        if aid and aid not in seen_ids:
            seen_ids.add(aid)
            merged.append(item)

    # Sort newest first; items with no timestamp go to the bottom
    merged.sort(
        key=lambda x: x["published"] or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return merged


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


def build_news_embeds(items: list[dict]) -> list[discord.Embed]:
    """Return one Discord Embed per article with headline as title and photo/video attached."""
    if not items:
        embed = discord.Embed(
            title="📰 NFL Headlines",
            description="No headlines available right now.",
            color=0x7A5C2E,
        )
        return [embed]

    embeds = []
    for item in items[:10]:  # Discord max 10 embeds per message
        headline = item.get("headline", "NFL News")
        url = item.get("url", "")
        source = item.get("source", "ESPN")
        desc = item.get("description", "")[:300]
        image_url = item.get("image_url", "")
        video_url = item.get("video_url", "")

        # Build description block
        parts = []
        if desc:
            parts.append(desc)
        if video_url:
            parts.append(f"📹 [Watch Video]({video_url})")
        if url:
            parts.append(f"[Read Full Article]({url})  •  **{source}**")
        else:
            parts.append(f"**{source}**")

        embed = discord.Embed(
            title=headline[:256],
            url=url or None,
            description="\n".join(parts)[:4096],
            color=0x7A5C2E,
        )

        if image_url:
            embed.set_image(url=image_url)

        embeds.append(embed)

    # Add a shared footer on the last embed
    if embeds:
        embeds[-1].set_footer(text="USO NFL Bot • ESPN")

    return embeds


# Keep old single-embed builder for backward-compat with trade/market commands
def build_news_embed(items: list[dict]) -> discord.Embed:
    embeds = build_news_embeds(items)
    return embeds[0] if embeds else discord.Embed(title="📰 NFL Headlines", color=0x7A5C2E)


async def get_team_schedule(team_abbr: str) -> dict:
    """Fetch full season schedule + record for a team. Returns {team, record, standing, season, games}."""
    slug = ROSTER_SLUGS.get(team_abbr, team_abbr.lower())
    data = await fetch_json(ESPN_TEAM_SCHEDULE_URL.format(team=slug))
    team_info = data.get("team", {})
    record = team_info.get("recordSummary", "0-0")
    season = team_info.get("seasonSummary", "")
    standing = team_info.get("standingSummary", "")

    _ET = ZoneInfo("America/New_York")
    games = []
    for event in data.get("events", []):
        comp = event.get("competitions", [{}])[0]
        week_text = event.get("week", {}).get("text", "")
        week_num = event.get("week", {}).get("number", 0)
        season_type = event.get("seasonType", {}).get("type", 2)

        # Parse game time
        date_str = event.get("date", "")
        game_dt = None
        if date_str:
            try:
                game_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00")).astimezone(_ET)
            except ValueError:
                pass

        # Find our team and the opponent
        competitors = comp.get("competitors", [])
        our_side = None
        opp_side = None
        for c in competitors:
            if c.get("team", {}).get("abbreviation", "").upper() == team_abbr.upper():
                our_side = c
            else:
                opp_side = c

        if not opp_side:
            continue

        opp_abbr = opp_side.get("team", {}).get("abbreviation", "???").upper()
        home_away = our_side.get("homeAway", "home") if our_side else "home"
        location = "vs" if home_away == "home" else "@"

        # Result
        completed = comp.get("status", {}).get("type", {}).get("completed", False)
        result = ""
        our_score = ""
        opp_score = ""
        winner = False
        if completed and our_side and opp_side:
            our_score = str(our_side.get("score", "") or "")
            opp_score = str(opp_side.get("score", "") or "")
            winner = our_side.get("winner", False)
            result = "W" if winner else "L"

        games.append({
            "week_num": week_num,
            "week_text": week_text,
            "season_type": season_type,
            "game_dt": game_dt,
            "opp_abbr": opp_abbr,
            "location": location,
            "completed": completed,
            "result": result,
            "our_score": our_score,
            "opp_score": opp_score,
        })

    return {
        "team_abbr": team_abbr,
        "team_name": TEAM_NAMES.get(team_abbr, team_abbr),
        "record": record,
        "season": season,
        "standing": standing,
        "games": games,
    }


def build_schedule_embed(schedule: dict, page: int = 0) -> discord.Embed:
    """Build a paginated schedule embed. Each page shows 9 weeks."""
    team_abbr = schedule["team_abbr"]
    team_name = schedule["team_name"]
    record = schedule["record"]
    season = schedule["season"]
    standing = schedule["standing"]
    games = schedule["games"]
    logo = TEAM_LOGOS.get(team_abbr, "")

    # Split into pages of 9 games
    page_size = 9
    total_pages = max(1, -(-len(games) // page_size))  # ceiling division
    page = max(0, min(page, total_pages - 1))
    page_games = games[page * page_size: (page + 1) * page_size]

    _ET = ZoneInfo("America/New_York")
    now_et = datetime.now(_ET)

    desc_parts = [f"**Record:** {record}"]
    if standing:
        desc_parts.append(f"**Standing:** {standing}")
    if season:
        desc_parts.append(f"**Season:** {season}")

    embed = discord.Embed(
        title=f"📅  {team_name} Schedule",
        description="  ".join(desc_parts),
        color=0x7A5C2E,
    )
    if logo:
        embed.set_thumbnail(url=logo)

    lines = []
    for g in page_games:
        week = g["week_text"] or f"Week {g['week_num']}"
        loc = g["location"]
        opp = g["opp_abbr"]

        if g["completed"]:
            icon = "✅" if g["result"] == "W" else "❌"
            score_str = f"{g['our_score']}-{g['opp_score']}"
            lines.append(f"`{week:<7}` {icon} **{g['result']}** {score_str:<7}  {loc} {opp}")
        else:
            if g["game_dt"]:
                # Mark next upcoming game
                is_next = g["game_dt"] > now_et
                date_fmt = g["game_dt"].strftime("%b %-d %-I:%M%p").replace("AM", "am").replace("PM", "pm")
                marker = "▶️" if is_next else "🕐"
                lines.append(f"`{week:<7}` {marker} {date_fmt:<17}  {loc} {opp}")
            else:
                lines.append(f"`{week:<7}` 🕐 TBD                {loc} {opp}")

    if lines:
        label = f"Games (Page {page + 1}/{total_pages})" if total_pages > 1 else "Games"
        embed.add_field(name=label, value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="Schedule", value="No games found.", inline=False)

    embed.set_footer(text=f"USO NFL Bot • ESPN  •  Page {page + 1}/{total_pages}")
    return embed


class ScheduleView(discord.ui.View):
    def __init__(self, schedule: dict):
        super().__init__(timeout=300)
        self.schedule = schedule
        self.page = 0
        games = schedule.get("games", [])
        self.total_pages = max(1, -(-len(games) // 9))
        self._refresh_buttons()

    def _refresh_buttons(self):
        self.prev_btn.disabled = self.page <= 0
        self.next_btn.disabled = self.page >= self.total_pages - 1

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self._refresh_buttons()
        await interaction.response.edit_message(embed=build_schedule_embed(self.schedule, self.page), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(self.total_pages - 1, self.page + 1)
        self._refresh_buttons()
        await interaction.response.edit_message(embed=build_schedule_embed(self.schedule, self.page), view=self)


def build_weekly_schedule_embed(games: list[dict], meta: dict) -> discord.Embed:
    """Full NFL week schedule — every game with records and result/time."""
    _ET = ZoneInfo("America/New_York")
    now_et = datetime.now(_ET)

    embed = discord.Embed(
        title=f"📅  NFL Schedule — {meta.get('display', 'This Week')}",
        color=0x7A5C2E,
    )

    if not games:
        embed.description = "No games scheduled this week."
        embed.set_footer(text="USO NFL Bot • ESPN")
        return embed

    lines = []
    for g in games:
        away = g["away_team"]
        home = g["home_team"]
        away_rec = g.get("away_record", "")
        home_rec = g.get("home_record", "")
        away_str = f"{away} ({away_rec})" if away_rec else away
        home_str = f"{home} ({home_rec})" if home_rec else home

        if g["completed"]:
            a_score = g.get("away_score", "0")
            h_score = g.get("home_score", "0")
            if g.get("away_winner"):
                winner_icon = "🏆"
                line = f"✅ **{away_str} {a_score}** — {h_score} {home_str}"
            else:
                winner_icon = "🏆"
                line = f"✅ {away_str} {a_score} — **{h_score} {home_str}**"
            _ = winner_icon  # suppress unused
        elif g.get("in_progress"):
            a_score = g.get("away_score", "0")
            h_score = g.get("home_score", "0")
            state = g.get("state", "LIVE")
            line = f"🔴 **LIVE** {away} {a_score} — {h_score} {home}  *{state}*"
        else:
            # Upcoming — state field holds the tip-off time string from ESPN
            state = g.get("state", "TBD")
            line = f"🕐 {away_str} @ {home_str}  —  {state}"

        lines.append(line)

    # Split into two equal fields so we stay under 1024-char limit
    mid = (len(lines) + 1) // 2
    embed.add_field(name="Games", value="\n".join(lines[:mid]), inline=False)
    if lines[mid:]:
        embed.add_field(name="\u200b", value="\n".join(lines[mid:]), inline=False)

    embed.set_footer(text="USO NFL Bot • ESPN  •  ◀ ▶ to browse weeks")
    return embed


class WeeklyScheduleView(discord.ui.View):
    """Week-by-week NFL schedule with Prev/Next and season-type buttons."""

    def __init__(self, games: list[dict], meta: dict):
        super().__init__(timeout=300)
        self.games = games
        self.meta = meta
        self._sync_buttons()

    def _sync_buttons(self):
        self.prev_btn.disabled = self.meta["week"] <= 1
        self.next_btn.disabled = self.meta["week"] >= self.meta["max_week"]
        self.pre_btn.style = (
            discord.ButtonStyle.primary if self.meta["season_type"] == 1
            else discord.ButtonStyle.secondary
        )
        self.reg_btn.style = (
            discord.ButtonStyle.primary if self.meta["season_type"] == 2
            else discord.ButtonStyle.secondary
        )
        self.playoff_btn.style = (
            discord.ButtonStyle.primary if self.meta["season_type"] == 3
            else discord.ButtonStyle.secondary
        )

    def build_embed(self) -> discord.Embed:
        return build_weekly_schedule_embed(self.games, self.meta)

    async def _fetch_and_update(self, interaction: discord.Interaction):
        self.games, self.meta = await get_scoreboard_data(
            week=self.meta["week"],
            season_type=self.meta["season_type"],
            year=self.meta["year"],
        )
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.meta["week"] -= 1
        await self._fetch_and_update(interaction)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.meta["week"] += 1
        await self._fetch_and_update(interaction)

    @discord.ui.button(label="Preseason", style=discord.ButtonStyle.secondary, row=1)
    async def pre_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.meta["season_type"] = 1
        self.meta["week"] = 1
        self.meta["max_week"] = 4
        await self._fetch_and_update(interaction)

    @discord.ui.button(label="Regular Season", style=discord.ButtonStyle.primary, row=1)
    async def reg_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.meta["season_type"] = 2
        self.meta["week"] = 1
        self.meta["max_week"] = 18
        await self._fetch_and_update(interaction)

    @discord.ui.button(label="Playoffs", style=discord.ButtonStyle.secondary, row=1)
    async def playoff_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.meta["season_type"] = 3
        self.meta["week"] = 1
        self.meta["max_week"] = 5
        await self._fetch_and_update(interaction)


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


async def team_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    current_lower = current.lower()
    choices = []
    for abbr, name in TEAM_NAMES.items():
        if current_lower in abbr.lower() or current_lower in name.lower():
            choices.append(app_commands.Choice(name=f"{name} ({abbr})", value=abbr))
    return choices[:25]


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


async def upsert_multi_embed_message(
    channel_id: int, message_id: int | None, embeds: list[discord.Embed]
) -> int | None:
    """Send or edit a single Discord message containing multiple embeds (max 10)."""
    if not channel_id:
        return message_id

    channel = bot.get_channel(channel_id)
    if channel is None:
        return message_id

    embeds = embeds[:10]  # Discord hard cap

    if message_id:
        try:
            msg = await channel.fetch_message(message_id)
            await msg.edit(embeds=embeds)
            return msg.id
        except discord.NotFound:
            pass

    msg = await channel.send(embeds=embeds)
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


@tasks.loop(minutes=2)
async def breaking_news_loop():
    """
    Every 2 minutes: fetch all articles from the last 24 hours.
    - First run: post everything from the last 24 h as a backlog, mark all seen.
    - Subsequent runs: post only brand-new articles (breaking news) immediately.
    """
    global seen_article_ids, _news_initialized, NEWS_CHANNEL_ID

    target_id = NEWS_CHANNEL_ID or NFLWATCH_CHANNEL_ID
    if not target_id:
        return
    channel = bot.get_channel(target_id)
    if channel is None:
        return

    recent = await get_all_recent_news(hours=24)
    if not recent:
        return

    if not _news_initialized:
        # First boot — post the full 24-hour backlog oldest-first so the channel
        # reads chronologically (newest ends up at the bottom).
        backlog = list(reversed(recent))
        for item in backlog:
            embed = _build_single_news_embed(item, breaking=False)
            try:
                await channel.send(embed=embed)
                await asyncio.sleep(0.75)  # stay under Discord rate limits
            except Exception:
                pass
            seen_article_ids.add(item["article_id"])
        _news_initialized = True
        return

    # Normal run — only post articles we haven't seen yet
    new_items = [i for i in recent if i["article_id"] not in seen_article_ids]
    # Post oldest first so breaking alerts appear in chronological order
    for item in reversed(new_items):
        embed = _build_single_news_embed(item, breaking=True)
        try:
            await channel.send(embed=embed)
            await asyncio.sleep(0.75)
        except Exception:
            pass
        seen_article_ids.add(item["article_id"])


def _build_single_news_embed(item: dict, breaking: bool = False) -> discord.Embed:
    """Build a rich embed for one news article."""
    headline = item.get("headline", "NFL News")
    url = item.get("url", "")
    source = item.get("source", "ESPN")
    desc = item.get("description", "")[:300]
    image_url = item.get("image_url", "")
    video_url = item.get("video_url", "")
    published: datetime | None = item.get("published")

    title_prefix = "🚨 BREAKING: " if breaking else "📰 "
    parts = []
    if desc:
        parts.append(desc)
    if video_url:
        parts.append(f"📹 [Watch Video]({video_url})")
    if url:
        parts.append(f"[Read Full Article]({url})  •  **{source}**")
    else:
        parts.append(f"**{source}**")

    embed = discord.Embed(
        title=f"{title_prefix}{headline}"[:256],
        url=url or None,
        description="\n".join(parts)[:4096],
        color=0xFF0000 if breaking else 0x7A5C2E,
    )
    if image_url:
        embed.set_image(url=image_url)
    if published:
        _ET = ZoneInfo("America/New_York")
        embed.set_footer(
            text=f"USO NFL Bot • {source} • {published.astimezone(_ET).strftime('%b %d, %Y %I:%M %p ET')}"
        )
    else:
        embed.set_footer(text=f"USO NFL Bot • {source}")
    return embed


# Legacy single-embed wrapper kept for trade/market commands
def news_loop():
    pass  # replaced by breaking_news_loop


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


@bot.tree.command(name="schedule", description="Show NFL schedule — pick a team's full season or the weekly NFL schedule")
@app_commands.describe(
    view="Choose Team Schedule or Weekly NFL Schedule",
    team="Team name or abbreviation — required for Team Schedule (e.g. KC, Dallas, Eagles)",
)
@app_commands.choices(view=[
    app_commands.Choice(name="Team Schedule", value="team"),
    app_commands.Choice(name="Weekly NFL Schedule", value="weekly"),
])
@app_commands.autocomplete(team=team_autocomplete)
async def schedule(
    interaction: discord.Interaction,
    view: str = "weekly",
    team: str | None = None,
):
    await interaction.response.defer()

    # ── Weekly NFL schedule ──────────────────────────────────────────
    if view == "weekly" and team is None:
        games, meta = await get_scoreboard_data()
        wview = WeeklyScheduleView(games, meta)
        await interaction.followup.send(embed=wview.build_embed(), view=wview)
        return

    # ── Team Schedule ────────────────────────────────────────────────
    # If user picked "weekly" but also provided a team, treat as team schedule
    if team is None:
        await interaction.followup.send(
            "❌ Please provide a team name when using **Team Schedule**.\n"
            "Example: `/schedule view:Team Schedule team:KC`",
            ephemeral=True,
        )
        return

    team = team.upper().strip()
    if team not in TEAM_NAMES:
        match = next((abbr for abbr, tname in TEAM_NAMES.items() if team in tname.upper()), None)
        if match:
            team = match
        else:
            await interaction.followup.send(
                f"❌ Unknown team `{team}`. Try an abbreviation like `KC`, `DAL`, or `PHI`.",
                ephemeral=True,
            )
            return

    try:
        schedule_data = await get_team_schedule(team)
    except Exception as e:
        await interaction.followup.send(f"❌ Could not fetch schedule: {e}", ephemeral=True)
        return

    sview = ScheduleView(schedule_data)
    sview._refresh_buttons()
    await interaction.followup.send(embed=build_schedule_embed(schedule_data, 0), view=sview)


@bot.tree.command(name="headlines", description="Show latest NFL headlines")
async def headlines(interaction: discord.Interaction):
    await interaction.response.defer()
    items = await get_news_items()
    await interaction.followup.send(embed=build_news_embed(items))


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


@bot.tree.command(name="nfl-leaders", description="Show NFL stat leaders for offense and defense")
async def leagueleaders(interaction: discord.Interaction):
    await interaction.response.defer()
    data = await get_league_leaders()
    view = LeagueLeadersView(data)
    await interaction.followup.send(embed=view.build_embed(), view=view)



@bot.tree.command(name="create-channel", description="Create a new text or voice channel [Admin only]")
@app_commands.describe(
    name="Channel name",
    kind="text or voice",
    category="Pick an existing category to place the channel in (optional)",
)
async def create_channel(
    interaction: discord.Interaction,
    name: str,
    kind: str = "text",
    category: discord.CategoryChannel | None = None,
):
    await interaction.response.defer()
    kind = kind.lower().strip()
    try:
        if kind == "voice":
            ch = await interaction.guild.create_voice_channel(name=name, category=category)
            ch_type = "🔊 Voice"
        else:
            ch = await interaction.guild.create_text_channel(name=name, category=category)
            ch_type = "💬 Text"

        loc = f" in **{category.name}**" if category else ""
        embed = discord.Embed(
            title="✅ Channel Created",
            description=f"{ch_type} channel {ch.mention} has been created{loc}.",
            color=0x7A5C2E,
        )
        embed.set_footer(text="USO Bot • Server Management")
        await interaction.followup.send(embed=embed)
    except discord.Forbidden:
        await interaction.followup.send("❌ I don't have permission to create channels. Make sure I have the **Manage Channels** permission.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)


@bot.tree.command(name="delete-channel", description="Delete an existing channel [Admin only]")
@app_commands.describe(channel="Pick the channel to delete")
async def delete_channel(
    interaction: discord.Interaction,
    channel: discord.TextChannel | discord.VoiceChannel | discord.StageChannel | discord.CategoryChannel | discord.ForumChannel,
):
    await interaction.response.defer()
    name = channel.name
    try:
        await channel.delete()
        embed = discord.Embed(
            title="🗑️ Channel Deleted",
            description=f"Channel **#{name}** has been deleted.",
            color=0x7A5C2E,
        )
        embed.set_footer(text="USO Bot • Server Management")
        await interaction.followup.send(embed=embed)
    except discord.Forbidden:
        await interaction.followup.send("❌ I don't have permission to delete channels. Make sure I have the **Manage Channels** permission.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)


@bot.tree.command(name="rename-server", description="Rename the server [Admin only]")
@app_commands.describe(name="New server name")
async def rename_server(interaction: discord.Interaction, name: str):
    await interaction.response.defer()
    try:
        old_name = interaction.guild.name
        await interaction.guild.edit(name=name)
        embed = discord.Embed(
            title="✅ Server Renamed",
            description=f"**{old_name}** → **{name}**",
            color=0x7A5C2E,
        )
        embed.set_footer(text="USO Bot • Server Management")
        await interaction.followup.send(embed=embed)
    except discord.Forbidden:
        await interaction.followup.send("❌ I don't have permission to rename the server. Make sure I have the **Manage Server** permission.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)


@bot.tree.command(name="create-category", description="Create a new channel category [Admin only]")
@app_commands.describe(name="Category name")
async def create_category(interaction: discord.Interaction, name: str):
    await interaction.response.defer()
    try:
        cat = await interaction.guild.create_category(name=name)
        embed = discord.Embed(
            title="✅ Category Created",
            description=f"Category **{cat.name}** has been created.",
            color=0x7A5C2E,
        )
        embed.set_footer(text="USO Bot • Server Management")
        await interaction.followup.send(embed=embed)
    except discord.Forbidden:
        await interaction.followup.send("❌ I don't have permission to create categories. Make sure I have the **Manage Channels** permission.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)


@bot.tree.command(name="set-news-channel", description="Set the channel where NFL news is automatically posted [Admin only]")
@app_commands.describe(channel='Mention the channel (#channel) or paste its ID. Leave blank to disable.')
async def set_news_channel(
    interaction: discord.Interaction,
    channel: Optional[str] = None,
):
    global NEWS_CHANNEL_ID, seen_article_ids, _news_initialized

    await interaction.response.defer(ephemeral=True)

    # Disable feed
    if channel is None:
        NEWS_CHANNEL_ID = 0
        embed = discord.Embed(
            title="🔕 News Feed Disabled",
            description="The NFL news feed has been turned off. Use `/set-news-channel` with a channel to re-enable it.",
            color=0x7A5C2E,
        )
        embed.set_footer(text="USO Bot • News Feed")
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    # Resolve channel from mention (<#ID>) or raw ID
    raw = channel.strip()
    match = re.match(r"<#(\d+)>", raw)
    channel_id = int(match.group(1)) if match else (int(raw) if raw.isdigit() else None)

    if channel_id is None:
        await interaction.followup.send(
            "❌ Couldn't parse that channel. Please mention the channel (e.g. `#general`) or paste its numeric ID.",
            ephemeral=True,
        )
        return

    resolved = interaction.guild.get_channel(channel_id) if interaction.guild else None
    if resolved is None:
        await interaction.followup.send(
            "❌ Channel not found in this server. Double-check the ID or mention.",
            ephemeral=True,
        )
        return

    NEWS_CHANNEL_ID = channel_id
    seen_article_ids = set()
    _news_initialized = False

    embed = discord.Embed(
        title="✅ News Feed Channel Set",
        description=(
            f"NFL news will now be automatically posted to {resolved.mention}.\n\n"
            "The last 24 hours of headlines will appear there shortly, "
            "then new articles will post as they break."
        ),
        color=0x7A5C2E,
    )
    embed.set_footer(text="USO Bot • News Feed")
    await interaction.followup.send(embed=embed, ephemeral=True)


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

    if not breaking_news_loop.is_running():
        breaking_news_loop.start()

    if not nflwatch_loop.is_running():
        nflwatch_loop.start()

    print(f"BOT READY - Logged in as {bot.user}")


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    msg = "❌ Something went wrong. Please try again."
    if isinstance(error, app_commands.MissingPermissions):
        msg = "❌ You don't have permission to use this command."
    elif isinstance(error, app_commands.BotMissingPermissions):
        msg = f"❌ I'm missing permissions: {', '.join(error.missing_permissions)}"
    elif isinstance(error, app_commands.CommandInvokeError):
        msg = f"❌ Error: {error.original}"
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        pass


TOS_HTML = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>USO Bot — Terms of Service</title>
<style>
  body{font-family:system-ui,sans-serif;max-width:760px;margin:40px auto;padding:0 24px;color:#1a1a1a;line-height:1.7}
  h1{color:#7A5C2E}h2{color:#333;margin-top:2em}
  footer{margin-top:3em;font-size:.85em;color:#888}
</style>
</head>
<body>
<h1>🏈 USO Bot — Terms of Service</h1>
<p><strong>Last updated: July 2025</strong></p>

<h2>1. Acceptance</h2>
<p>By adding USO Bot to your Discord server or using any of its commands, you agree to these Terms of Service. If you do not agree, do not use the bot.</p>

<h2>2. Description of Service</h2>
<p>USO Bot provides NFL-related information including live scores, player statistics, trade headlines, and league leaders. All data is sourced from publicly available APIs (primarily ESPN). The bot does not guarantee the accuracy, completeness, or timeliness of any information provided.</p>

<h2>3. Acceptable Use</h2>
<p>You agree not to:</p>
<ul>
  <li>Use the bot for any unlawful purpose</li>
  <li>Attempt to exploit, abuse, or disrupt the bot or its hosting infrastructure</li>
  <li>Use the bot to harass or harm others</li>
  <li>Reverse engineer or attempt to extract source code through the bot's interface</li>
</ul>

<h2>4. Data &amp; Privacy</h2>
<p>USO Bot does not collect, store, or share personal data about users. Commands are processed in real time and no message content or user identifiers are retained. See our <a href="/privacy">Privacy Policy</a> for details.</p>

<h2>5. Disclaimer of Warranties</h2>
<p>The bot is provided "as is" without warranty of any kind. We make no guarantees regarding uptime, data accuracy, or fitness for a particular purpose. NFL statistics and news are provided for informational purposes only.</p>

<h2>6. Limitation of Liability</h2>
<p>The creators of USO Bot are not liable for any direct, indirect, incidental, or consequential damages arising from your use of the bot.</p>

<h2>7. Changes to Terms</h2>
<p>These terms may be updated at any time. Continued use of the bot after changes constitutes acceptance of the revised terms.</p>

<h2>8. Contact</h2>
<p>For questions or concerns, please reach out through your Discord server's administration.</p>

<footer>USO Bot &mdash; Unofficial. Not affiliated with the NFL or ESPN.</footer>
</body>
</html>"""

PRIVACY_HTML = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>USO Bot — Privacy Policy</title>
<style>
  body{font-family:system-ui,sans-serif;max-width:760px;margin:40px auto;padding:0 24px;color:#1a1a1a;line-height:1.7}
  h1{color:#7A5C2E}h2{color:#333;margin-top:2em}
  footer{margin-top:3em;font-size:.85em;color:#888}
</style>
</head>
<body>
<h1>🏈 USO Bot — Privacy Policy</h1>
<p><strong>Last updated: July 2025</strong></p>

<h2>1. Information We Collect</h2>
<p>USO Bot does <strong>not</strong> collect or store any personal information. Specifically:</p>
<ul>
  <li>We do not log Discord usernames, IDs, or message content</li>
  <li>We do not store command history or usage data</li>
  <li>We do not use cookies or tracking technologies</li>
</ul>

<h2>2. How the Bot Works</h2>
<p>When you use a slash command, the bot fetches data from third-party sports APIs (such as ESPN) and returns it directly to your Discord channel. No data from your request is retained after the response is sent.</p>

<h2>3. Third-Party Services</h2>
<p>The bot retrieves data from ESPN's public APIs and may fall back to NFL.com or Yahoo Sports. Your use of this bot is also subject to Discord's <a href="https://discord.com/privacy" target="_blank">Privacy Policy</a>.</p>

<h2>4. Children's Privacy</h2>
<p>This bot is not directed at children under 13. We do not knowingly collect information from children.</p>

<h2>5. Changes</h2>
<p>This policy may be updated periodically. Continued use of the bot constitutes acceptance of any changes.</p>

<h2>6. Contact</h2>
<p>Questions about this policy can be directed to your server's administration.</p>

<footer>USO Bot &mdash; Unofficial. Not affiliated with the NFL or ESPN.</footer>
</body>
</html>"""


async def handle_tos(request):
    return aiohttp_web.Response(text=TOS_HTML, content_type="text/html")


async def handle_privacy(request):
    return aiohttp_web.Response(text=PRIVACY_HTML, content_type="text/html")


async def handle_root(request):
    return aiohttp_web.Response(text="<h2>USO NFL Bot is running.</h2>", content_type="text/html")


async def run_web_server():
    app = aiohttp_web.Application()
    app.router.add_get("/", handle_root)
    app.router.add_get("/tos", handle_tos)
    app.router.add_get("/privacy", handle_privacy)
    runner = aiohttp_web.AppRunner(app)
    await runner.setup()
    site = aiohttp_web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()


async def main():
    global session
    session = aiohttp.ClientSession()
    await run_web_server()
    async with bot:
        await bot.start(TOKEN)


if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing. Add it in Replit Secrets.")

try:
    asyncio.run(main())
finally:
    async def _close():
        global session
        if session and not session.closed:
            await session.close()
    asyncio.run(_close())
