import os
import re
import html
import time
import random
import asyncio
from dotenv import load_dotenv

load_dotenv()
import logging
import contextvars
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

# ── AI modules ────────────────────────────────────────────────────────────────
from ai.settings  import init_db, get_server_settings, upsert_server_settings
from ai.memory    import recall_server, recall_user, remember_user, forget_user, clear_conversation
from ai.brain     import AIBrain
from ai import conversation as _conv
from ai import cooldowns    as _cd
from ai.scheduler import run_checkins
from ai.security  import drain_pending_alerts, ALERT_WINDOW_MINUTES

# ── Server manager feature ────────────────────────────────────────────────────
from features.serverManager.db      import init_server_manager_db, get_server_manager_config, upsert_server_manager_config
from features.serverManager.handler import handle_member_join, handle_member_remove
from features.announcements import (
    init_announcements_db,
    add_scheduled_announcement,
    get_scheduled_announcements,
    get_all_enabled_announcements,
    remove_scheduled_announcement,
    update_last_sent,
    TZ_MAP,
)

# Context vars so the tools executor can access guild/author without changing AIBrain's interface
_ctx_guild  = contextvars.ContextVar("sm_guild",  default=None)
_ctx_author = contextvars.ContextVar("sm_author", default=None)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("uso")

# ── Startup dependency check ───────────────────────────────────────────────────
try:
    import ddgs as _ddgs_check  # noqa: F401
except ImportError:
    log.warning(
        "⚠️  'ddgs' package is not installed — the web_search AI tool will fail. "
        "Run `uv sync` or add ddgs to pyproject.toml dependencies."
    )

TOKEN = os.getenv("DISCORD_TOKEN")

# Optional auto-post channels. Set to your Discord channel ID to enable.
SCORES_CHANNEL_ID = 0
NEWS_CHANNEL_ID = 0          # updated at runtime via /set-news-channel
ALERTS_CHANNEL_ID = 0
NFLWATCH_CHANNEL_ID = 1529435544822743040  # Auto-posts NFL market watch at 8am and 5pm ET daily

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
intents.message_content = True   # enabled — Message Content Intent toggled on in Dev Portal
intents.members = True            # enabled — Server Members Intent (required for on_member_join/remove)
bot = commands.Bot(command_prefix="!", intents=intents)

# ── AI brain — initialised in on_ready once OPENAI_API_KEY is confirmed ───────
ai_brain: AIBrain | None = None

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


async def _dispatch_security_alerts() -> None:
    """Drain pending security alerts and DM each affected guild's owner.

    Called after process_message returns whenever a blocked attempt may have
    pushed a user over the repeat-abuse threshold.
    """
    alerts = drain_pending_alerts()
    for alert in alerts:
        guild = bot.get_guild(int(alert["guild_id"]))
        if guild is None:
            log.warning("[SECURITY] Alert: guild %s not in cache, skipping DM", alert["guild_id"])
            continue
        owner = guild.owner
        if owner is None:
            log.warning("[SECURITY] Alert: owner not cached for guild %s", guild.name)
            continue
        snippets_fmt = "\n".join(f"• {s}" for s in alert["snippets"])
        dm_text = (
            f"🚨 **Security Alert — {guild.name}**\n"
            f"User <@{alert['user_id']}> (`{alert['user_id']}`) has made "
            f"**{alert['count']}** blocked proprietary-information requests "
            f"in the last {ALERT_WINDOW_MINUTES} minutes.\n\n"
            f"**Sample blocked messages:**\n{snippets_fmt}\n\n"
            f"_The user's counter has been reset. You will be alerted again if "
            f"they continue after a fresh {ALERT_WINDOW_MINUTES}-minute window._"
        )
        try:
            await owner.send(dm_text)
            log.warning(
                "[SECURITY] Owner DM sent — guild=%s user=%s attempts=%d",
                alert["guild_id"], alert["user_id"], alert["count"],
            )
        except Exception as exc:
            log.warning(
                "[SECURITY] Failed to DM owner of guild %s: %s",
                alert["guild_id"], exc,
            )


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


async def get_league_leaders(year: int | None = None, season_type: int = 2) -> dict:
    if year is None:
        year = datetime.now().year
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
        embed.set_footer(text="🔴 LIVE • Uce")
    else:
        embed.set_footer(text="Uce")

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
        embeds[-1].set_footer(text="Uce • ESPN")

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

    embed.set_footer(text=f"Uce • ESPN  •  Page {page + 1}/{total_pages}")
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
        embed.set_footer(text="Uce • ESPN")
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

    embed.set_footer(text="Uce • ESPN  •  ◀ ▶ to browse weeks")
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
    embed.set_footer(text="Uce")
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
    embed.set_footer(text="Uce • Live market watch")
    return embed


def build_leaders_embed(data: dict, mode: str) -> discord.Embed:
    year = data.get("year", datetime.now().year)
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

    embed.set_footer(text="Uce • ESPN")
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
        embed.set_footer(text=f"Uce • {source_label}", icon_url=player["team_logo"])
    else:
        embed.set_footer(text=f"Uce • {source_label}")

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

    embed.set_footer(text=f"Season {page + 1}/{total} • Uce")
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

        embed.set_footer(text="Uce")
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
    - First run: mark all current articles seen without posting (avoid backlog flood).
    - Subsequent runs: post only brand-new articles to every configured guild channel.

    Channel priority per guild:
      1. headlines_channel_id stored in server_settings (set via /headlines-channel)
      2. Global NEWS_CHANNEL_ID fallback (legacy /set-news-channel)
      3. Hardcoded NFLWATCH_CHANNEL_ID fallback
    """
    global seen_article_ids, _news_initialized, NEWS_CHANNEL_ID

    recent = await get_all_recent_news(hours=24)
    if not recent:
        return

    if not _news_initialized:
        # First boot — mark all current articles as seen without posting them.
        for item in recent:
            seen_article_ids.add(item["article_id"])
        _news_initialized = True
        return

    new_items = [i for i in recent if i["article_id"] not in seen_article_ids]
    if not new_items:
        return

    # Build list of target channels — one per guild, respecting per-guild config
    target_channels: list[discord.TextChannel] = []
    guilds_covered: set[int] = set()

    for guild in bot.guilds:
        guild_id = str(guild.id)
        try:
            cfg = get_server_settings(guild_id)
        except Exception:
            cfg = {}
        ch_id = cfg.get("headlines_channel_id")

        if ch_id:
            channel = guild.get_channel(int(ch_id))
            if channel is None:
                # Channel was deleted — clear setting and notify server owner
                try:
                    upsert_server_settings(guild_id, headlines_channel_id=None)
                    if guild.owner:
                        await guild.owner.send(
                            "⚠️ **Uce — Headlines channel removed**\n"
                            "The headlines channel I was posting to no longer exists. "
                            "Automatic headline posting has been paused.\n"
                            "Use `/headlines-channel set` to choose a new channel."
                        )
                except Exception:
                    pass
                continue
            target_channels.append(channel)
            guilds_covered.add(guild.id)

    # Global fallback for any guild not covered by per-guild config
    fallback_id = NEWS_CHANNEL_ID or NFLWATCH_CHANNEL_ID
    if fallback_id:
        fallback_ch = bot.get_channel(fallback_id)
        if (
            fallback_ch is not None
            and isinstance(fallback_ch, discord.TextChannel)
            and fallback_ch.guild.id not in guilds_covered
        ):
            target_channels.append(fallback_ch)

    if not target_channels:
        return

    # Post oldest-first to each channel so alerts appear in chronological order
    for channel in target_channels:
        for item in reversed(new_items):
            embed = _build_single_news_embed(item, breaking=True)
            try:
                await channel.send(embed=embed)
                await asyncio.sleep(0.75)
            except Exception:
                pass

    # Mark all new items seen after posting to all channels
    for item in new_items:
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
            text=f"Uce • {source} • {published.astimezone(_ET).strftime('%b %d, %Y %I:%M %p ET')}"
        )
    else:
        embed.set_footer(text=f"Uce • {source}")
    return embed


# Legacy single-embed wrapper kept for trade/market commands
def news_loop():
    pass  # replaced by breaking_news_loop


_EASTERN = ZoneInfo("America/New_York")


@tasks.loop(minutes=1)
async def announcements_loop():
    """Fire any scheduled announcements that are due on the current minute."""
    rows = get_all_enabled_announcements()
    if not rows:
        return

    now_utc = datetime.now(timezone.utc)

    for row in rows:
        try:
            tz = ZoneInfo(row["timezone"])
            now_local = now_utc.astimezone(tz)
            current_time_str = now_local.strftime("%H:%M")

            if current_time_str != row["time_str"]:
                continue

            # Dedup: skip if already sent within this calendar day (daily) or
            # within this week's occurrence (weekly).
            last_sent_dt = datetime.fromtimestamp(row["last_sent"], tz=tz) if row["last_sent"] else None

            if row["frequency"] == "daily":
                if last_sent_dt and last_sent_dt.date() == now_local.date():
                    continue  # already fired today
            elif row["frequency"] == "weekly":
                current_day = now_local.strftime("%A").lower()
                if row["day_of_week"] and current_day != row["day_of_week"]:
                    continue
                if last_sent_dt and last_sent_dt.date() == now_local.date():
                    continue  # already fired this week's occurrence
            else:
                continue  # unknown frequency — skip

            guild = bot.get_guild(int(row["guild_id"]))
            if guild is None:
                continue
            channel = guild.get_channel(int(row["channel_id"]))
            if channel is None:
                continue

            bot_perms = channel.permissions_for(guild.me)
            if not bot_perms.send_messages or not bot_perms.embed_links:
                continue

            embed = discord.Embed(
                description=row["message"][:4096],
                color=0x1E90FF,
                timestamp=now_utc,
            )
            embed.set_footer(text="📢 Scheduled Announcement")
            await channel.send(embed=embed)
            update_last_sent(row["id"])

        except Exception as exc:
            log.warning("announcements_loop error for id=%s: %s", row.get("id"), exc)


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
    embed.set_footer(text=f"Uce • Auto-posted {now_et.strftime('%I:%M %p ET • %b %d, %Y')}")
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


@bot.tree.command(
    name="headlines-channel",
    description="Configure which channel receives automatic NFL headline posts [Admin only]",
)
@app_commands.describe(
    action="set — pick a channel | view — see current setting | disable — turn off auto-posts",
    channel="Channel to receive automatic headlines (required when action is 'set')",
)
@app_commands.choices(action=[
    app_commands.Choice(name="set",     value="set"),
    app_commands.Choice(name="view",    value="view"),
    app_commands.Choice(name="disable", value="disable"),
])
async def headlines_channel_cmd(
    interaction: discord.Interaction,
    action: str,
    channel: discord.TextChannel | None = None,
):
    if not interaction.guild:
        await interaction.response.send_message(
            "This command only works inside a server.", ephemeral=True
        )
        return

    perms = interaction.user.guild_permissions
    if not (perms.administrator or perms.manage_guild):
        await interaction.response.send_message(
            "You need **Administrator** or **Manage Server** permission to change this setting.",
            ephemeral=True,
        )
        return

    guild_id = str(interaction.guild.id)

    if action == "view":
        cfg    = get_server_settings(guild_id)
        ch_id  = cfg.get("headlines_channel_id")
        if ch_id:
            ch = interaction.guild.get_channel(int(ch_id))
            if ch:
                await interaction.response.send_message(
                    f"📰 Automatic headlines are posting to {ch.mention}.", ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "⚠️ The configured headlines channel no longer exists. "
                    "Use `/headlines-channel set` to pick a new one.",
                    ephemeral=True,
                )
        else:
            fallback_id = NEWS_CHANNEL_ID or NFLWATCH_CHANNEL_ID
            fallback_ch = bot.get_channel(fallback_id) if fallback_id else None
            if fallback_ch:
                await interaction.response.send_message(
                    f"📰 No per-server channel configured — using the default fallback {fallback_ch.mention}. "
                    f"Use `/headlines-channel set` to choose a specific channel.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "📰 No headlines channel is configured. "
                    "Use `/headlines-channel set #channel` to enable automatic posts.",
                    ephemeral=True,
                )
        return

    if action == "disable":
        upsert_server_settings(guild_id, headlines_channel_id=None)
        await interaction.response.send_message(
            "📰 Automatic headline posting has been disabled for this server.",
            ephemeral=True,
        )
        return

    # action == "set"
    if channel is None:
        await interaction.response.send_message(
            "Please specify a channel. Example: `/headlines-channel set #nfl-news`",
            ephemeral=True,
        )
        return

    bot_perms = channel.permissions_for(interaction.guild.me)
    if not bot_perms.send_messages or not bot_perms.embed_links:
        await interaction.response.send_message(
            f"❌ I'm missing **Send Messages** or **Embed Links** permission in {channel.mention}. "
            "Fix my channel permissions and try again.",
            ephemeral=True,
        )
        return

    upsert_server_settings(guild_id, headlines_channel_id=str(channel.id))
    await interaction.response.send_message(
        f"✅ NFL headlines will now be posted automatically to {channel.mention}.",
        ephemeral=True,
    )


@bot.tree.command(
    name="announce",
    description="Post an announcement to a channel as a bot embed [Admin only]",
)
@app_commands.describe(
    channel="Channel to post the announcement in",
    message="The announcement text",
    title="Optional embed title (defaults to '📢 Announcement')",
)
async def announce_cmd(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    message: str,
    title: str = "📢 Announcement",
):
    if not interaction.guild:
        await interaction.response.send_message(
            "This command only works inside a server.", ephemeral=True
        )
        return

    perms = interaction.user.guild_permissions
    if not (perms.administrator or perms.manage_guild):
        await interaction.response.send_message(
            "You need **Administrator** or **Manage Server** permission to post announcements.",
            ephemeral=True,
        )
        return

    bot_perms = channel.permissions_for(interaction.guild.me)
    if not bot_perms.send_messages or not bot_perms.embed_links:
        await interaction.response.send_message(
            f"❌ I'm missing **Send Messages** or **Embed Links** permission in {channel.mention}.",
            ephemeral=True,
        )
        return

    embed = discord.Embed(
        title=title[:256],
        description=message[:4096],
        color=0x1E90FF,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text=f"Announced by {interaction.user.display_name}")

    await channel.send(embed=embed)
    await interaction.response.send_message(
        f"✅ Announcement posted to {channel.mention}.", ephemeral=True
    )


@bot.tree.command(
    name="announcement-schedule",
    description="Manage scheduled announcements for this server [Admin only]",
)
@app_commands.describe(
    action="add — create a schedule | list — view schedules | remove — delete a schedule",
    channel="Channel to post in (required for add)",
    message="Announcement text (required for add)",
    frequency="How often to post (required for add)",
    time="24-hour time to post, e.g. 14:30 (required for add)",
    day="Day of week for weekly announcements, e.g. monday (required for weekly)",
    timezone="Timezone for the schedule (default ET)",
    id="Schedule ID to remove (required for remove)",
)
@app_commands.choices(
    action=[
        app_commands.Choice(name="add",    value="add"),
        app_commands.Choice(name="list",   value="list"),
        app_commands.Choice(name="remove", value="remove"),
    ],
    frequency=[
        app_commands.Choice(name="daily",  value="daily"),
        app_commands.Choice(name="weekly", value="weekly"),
    ],
    day=[
        app_commands.Choice(name="Monday",    value="monday"),
        app_commands.Choice(name="Tuesday",   value="tuesday"),
        app_commands.Choice(name="Wednesday", value="wednesday"),
        app_commands.Choice(name="Thursday",  value="thursday"),
        app_commands.Choice(name="Friday",    value="friday"),
        app_commands.Choice(name="Saturday",  value="saturday"),
        app_commands.Choice(name="Sunday",    value="sunday"),
    ],
    timezone=[
        app_commands.Choice(name="ET — Eastern",  value="ET"),
        app_commands.Choice(name="CT — Central",  value="CT"),
        app_commands.Choice(name="MT — Mountain", value="MT"),
        app_commands.Choice(name="PT — Pacific",  value="PT"),
        app_commands.Choice(name="UTC",           value="UTC"),
    ],
)
async def announcement_schedule_cmd(
    interaction: discord.Interaction,
    action: str,
    channel: discord.TextChannel | None = None,
    message: str | None = None,
    frequency: str | None = None,
    time: str | None = None,
    day: str | None = None,
    timezone: str = "ET",
    id: int | None = None,
):
    if not interaction.guild:
        await interaction.response.send_message(
            "This command only works inside a server.", ephemeral=True
        )
        return

    perms = interaction.user.guild_permissions
    if not (perms.administrator or perms.manage_guild):
        await interaction.response.send_message(
            "You need **Administrator** or **Manage Server** permission to manage schedules.",
            ephemeral=True,
        )
        return

    guild_id = str(interaction.guild.id)

    # ── list ────────────────────────────────────────────────────────────────
    if action == "list":
        rows = get_scheduled_announcements(guild_id)
        if not rows:
            await interaction.response.send_message(
                "📋 No scheduled announcements are set up for this server.\n"
                "Use `/announcement-schedule add` to create one.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="📋 Scheduled Announcements",
            color=0x1E90FF,
        )
        for row in rows:
            ch = interaction.guild.get_channel(int(row["channel_id"]))
            ch_str = ch.mention if ch else f"<deleted channel {row['channel_id']}>"
            sched = (
                f"{row['frequency'].capitalize()} at {row['time_str']} {row['timezone']}"
                + (f" on {row['day_of_week'].capitalize()}" if row["day_of_week"] else "")
            )
            preview = row["message"][:80] + ("…" if len(row["message"]) > 80 else "")
            embed.add_field(
                name=f"ID {row['id']} — {sched}",
                value=f"Channel: {ch_str}\nMessage: {preview}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # ── remove ───────────────────────────────────────────────────────────────
    if action == "remove":
        if id is None:
            await interaction.response.send_message(
                "Please provide the schedule **ID** to remove. "
                "Use `/announcement-schedule list` to see IDs.",
                ephemeral=True,
            )
            return
        removed = remove_scheduled_announcement(guild_id, id)
        if removed:
            await interaction.response.send_message(
                f"🗑️ Schedule **#{id}** has been removed.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"❌ No schedule with ID **#{id}** found for this server.", ephemeral=True
            )
        return

    # ── add ──────────────────────────────────────────────────────────────────
    missing = []
    if channel is None:  missing.append("`channel`")
    if message is None:  missing.append("`message`")
    if frequency is None: missing.append("`frequency`")
    if time is None:     missing.append("`time`")
    if frequency == "weekly" and day is None:
        missing.append("`day` (required for weekly)")
    if missing:
        await interaction.response.send_message(
            f"Missing required fields for **add**: {', '.join(missing)}.",
            ephemeral=True,
        )
        return

    # Validate HH:MM format
    import re as _re
    if not _re.match(r"^\d{1,2}:\d{2}$", time):
        await interaction.response.send_message(
            "❌ **time** must be in 24-hour format, e.g. `14:30` for 2:30 PM.",
            ephemeral=True,
        )
        return
    hh, mm = time.split(":")
    if not (0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
        await interaction.response.send_message(
            "❌ **time** is out of range. Use 00:00–23:59.",
            ephemeral=True,
        )
        return
    time_str = f"{int(hh):02d}:{mm}"  # normalise to zero-padded HH:MM

    bot_perms = channel.permissions_for(interaction.guild.me)
    if not bot_perms.send_messages or not bot_perms.embed_links:
        await interaction.response.send_message(
            f"❌ I'm missing **Send Messages** or **Embed Links** permission in {channel.mention}.",
            ephemeral=True,
        )
        return

    iana_tz = TZ_MAP.get(timezone, "America/New_York")
    ann_id = add_scheduled_announcement(
        guild_id=guild_id,
        channel_id=str(channel.id),
        message=message,
        frequency=frequency,
        time_str=time_str,
        day_of_week=day,
        tz=iana_tz,
        created_by=str(interaction.user),
    )

    sched_str = (
        f"Every **{day.capitalize()}** at **{time_str} {timezone}**"
        if frequency == "weekly"
        else f"Every day at **{time_str} {timezone}**"
    )
    await interaction.response.send_message(
        f"✅ Schedule **#{ann_id}** created — {sched_str} in {channel.mention}.",
        ephemeral=True,
    )


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
        embed.set_footer(text="Uce • Server Management")
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
        embed.set_footer(text="Uce • Server Management")
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
        embed.set_footer(text="Uce • Server Management")
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
        embed.set_footer(text="Uce • Server Management")
        await interaction.followup.send(embed=embed)
    except discord.Forbidden:
        await interaction.followup.send("❌ I don't have permission to create categories. Make sure I have the **Manage Channels** permission.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
#  AI — Tools executor (calls existing bot data functions, returns plain text)
# ══════════════════════════════════════════════════════════════════════════════

_MAGIC_8 = [
    "It is certain.", "Without a doubt.", "You may rely on it.",
    "Yes, definitely.", "It is decidedly so.", "As I see it, yes.",
    "Ask again later.", "Better not tell you now.", "Cannot predict now.",
    "Concentrate and ask again.", "Don't count on it.", "My reply is no.",
    "Outlook not so good.", "Very doubtful.", "My sources say no.",
]

_HOT_TAKES = [
    "Thursday Night Football ruins more seasons than injuries do.",
    "Kickers are the most underrated players in football. Change my mind.",
    "A great offensive line wins championships, not a great QB.",
    "The two-point conversion should be worth 3 points.",
    "Pre-snap penalties are ruining the flow of the modern NFL.",
    "Punters are the most overlooked athletes in all of sports.",
    "Any team that drafts a QB in round 1 is setting themselves up for failure.",
    "Home-field advantage in the playoffs is massively overrated.",
    "Pass interference should be a 15-yard penalty, not a spot foul.",
    "The Pro Bowl is unwatchable and should be replaced with skills competitions.",
]

_NFL_TRIVIA = [
    ("Who holds the NFL record for most career passing yards?", "Tom Brady (89,214 yards as of retirement)"),
    ("Which team has won the most Super Bowls?", "New England Patriots with 6 Super Bowl wins"),
    ("Who was the first QB to throw for 5,000 yards in a single season?", "Dan Marino in 1984 (5,084 yards)"),
    ("Which defensive player holds the record for most career sacks?", "Bruce Smith with 200 career sacks"),
    ("What year was the Super Bowl first played?", "1967 (Super Bowl I, Packers vs Chiefs)"),
    ("Who kicked the longest field goal in NFL history?", "Matt Prater — 64 yards in 2013"),
    ("Which team went 16-0 in a regular season?", "The 2007 New England Patriots"),
    ("Who holds the single-season rushing yards record?", "Eric Dickerson — 2,105 yards in 1984"),
]


async def _ai_tools_executor(fn_name: str, fn_args: dict) -> str:
    """Dispatch AI tool calls to existing bot data functions. Returns plain text."""
    try:
        if fn_name == "get_scoreboard":
            games, meta = await get_scoreboard_data()
            if not games:
                return "No games scheduled this week."
            lines = [f"**{meta.get('display', 'NFL Scoreboard')}**"]
            for g in games[:10]:
                a, h = g["away_team"], g["home_team"]
                score = f"{a} {g['away_score']} – {g['home_score']} {h}"
                lines.append(f"{score}  ({g['state']})")
            return "\n".join(lines)

        elif fn_name == "get_headlines":
            items = await get_news_items(5)
            if not items:
                return "No headlines right now."
            return "\n".join(
                f"• {i['headline']}  [{i.get('source','ESPN')}]" for i in items
            )

        elif fn_name == "get_player_stats":
            name = fn_args.get("player_name", "")
            profile = await fetch_full_player_profile(name)
            if not profile:
                return f"Couldn't find a player named '{name}'."
            team = TEAM_NAMES.get(profile.get("team", ""), profile.get("team", "N/A"))
            pos  = profile.get("position", "N/A")
            num  = profile.get("jersey") or "N/A"
            stats_info = ""
            blocks = profile.get("stats") or []
            for block in blocks[:1]:
                lines = []
                for s in (block.get("stats") or [])[:4]:
                    if isinstance(s, dict):
                        n = s.get("displayName") or s.get("name")
                        v = s.get("displayValue") or s.get("value")
                        if n and v is not None:
                            lines.append(f"{n}: {v}")
                if lines:
                    stats_info = "  |  " + " • ".join(lines)
            return f"**{profile['name']}** — {pos}, {team}, #{num}{stats_info}"

        elif fn_name == "get_team_schedule":
            team = fn_args.get("team", "").upper().strip()
            if team not in TEAM_NAMES:
                match = next((a for a, n in TEAM_NAMES.items() if team in n.upper()), None)
                if match:
                    team = match
                else:
                    return f"Unknown team '{fn_args.get('team')}'. Try KC, DAL, SF, etc."
            sched = await get_team_schedule(team)
            recent   = [g for g in sched["games"] if g["completed"]][-3:]
            upcoming = [g for g in sched["games"] if not g["completed"]][:3]
            lines = [f"**{TEAM_NAMES[team]}** ({sched['record']})"]
            for g in recent:
                lines.append(f"  {'✅' if g['result']=='W' else '❌'} {g['result']} {g['our_score']}-{g['opp_score']} {g['location']} {g['opp_abbr']}")
            for g in upcoming:
                date = g["game_dt"].strftime("%b %-d") if g.get("game_dt") else "TBD"
                lines.append(f"  🗓 {date}  {g['location']} {g['opp_abbr']}")
            return "\n".join(lines)

        elif fn_name == "get_trade_news":
            sections = await get_trade_tracker_sections(limit=6)
            lines = []
            for item in sections.get("completed", [])[:2]:
                lines.append(f"✅ {item['headline']}")
            for item in sections.get("rumors", [])[:2]:
                lines.append(f"👀 {item['headline']}")
            return "\n".join(lines) if lines else "No trade news at the moment."

        elif fn_name == "get_league_leaders":
            data = await get_league_leaders()
            offense = data.get("offense", {})
            lines = []
            for cat in ["Passing Yards", "Rushing Yards", "Receiving Yards"]:
                players = offense.get(cat, [])
                if players:
                    p = players[0]
                    lines.append(f"**{cat}:** {p['name']} ({p['team']}) — {p['value']}")
            return "\n".join(lines) if lines else "No leaders data available right now."

        elif fn_name == "coin_flip":
            return random.choice(["🪙 **Heads!**", "🪙 **Tails!**"])

        elif fn_name == "magic_8_ball":
            return f"🎱 {random.choice(_MAGIC_8)}"

        elif fn_name == "hot_take":
            return f"🔥 **Hot Take:** {random.choice(_HOT_TAKES)}"

        elif fn_name == "trivia":
            q, a = random.choice(_NFL_TRIVIA)
            return f"🏈 **NFL Trivia:** {q}\n||{a}||"

        # ── Server management tools ──────────────────────────────────────────
        elif fn_name == "get_server_roles":
            guild = _ctx_guild.get()
            if guild is None:
                return "Server information is not available right now."
            roles = [r for r in guild.roles if not r.is_default()]
            if not roles:
                return "This server has no custom roles yet."
            lines = [f"• **{r.name}** (ID: `{r.id}`)" for r in sorted(roles, key=lambda r: r.position, reverse=True)]
            return "**Server roles:**\n" + "\n".join(lines)

        elif fn_name == "read_server_config":
            guild = _ctx_guild.get()
            if guild is None:
                return "Server information is not available right now."
            guild_id = str(guild.id)
            config   = get_server_manager_config(guild_id)
            settings = get_server_settings(guild_id)
            lines    = []

            ar_ids = config.get("auto_roles", [])
            if ar_ids:
                role_names = []
                for rid in ar_ids:
                    r = guild.get_role(int(rid))
                    role_names.append(r.name if r else f"Unknown ({rid})")
                lines.append(f"**Auto-roles:** {', '.join(role_names)}")
            else:
                lines.append("**Auto-roles:** None configured")

            # Welcome
            w_status = "✅ Enabled" if config["welcome_enabled"] else "❌ Disabled"
            w_ch_id  = config.get("welcome_channel_id")
            if w_ch_id:
                w_ch = guild.get_channel(int(w_ch_id))
                w_ch_str = f"#{w_ch.name}" if w_ch else f"⚠️ Deleted channel (ID: {w_ch_id})"
            else:
                ai_chans  = settings.get("ai_channels", [])
                w_ch_str  = f"#{guild.get_channel(int(ai_chans[0])).name} (AI channel fallback)" if ai_chans and guild.get_channel(int(ai_chans[0])) else "None — use /ai-channel to set one"
            lines.append(f"**Welcome messages:** {w_status}")
            lines.append(f"**Welcome channel:** {w_ch_str}")
            lines.append(f"**Welcome message:** {config['welcome_message']}")

            # Goodbye
            g_status = "✅ Enabled" if config["goodbye_enabled"] else "❌ Disabled"
            g_ch_id  = config.get("goodbye_channel_id")
            if g_ch_id:
                g_ch = guild.get_channel(int(g_ch_id))
                g_ch_str = f"#{g_ch.name}" if g_ch else f"⚠️ Deleted channel (ID: {g_ch_id})"
            else:
                ai_chans  = settings.get("ai_channels", [])
                g_ch_str  = f"#{guild.get_channel(int(ai_chans[0])).name} (AI channel fallback)" if ai_chans and guild.get_channel(int(ai_chans[0])) else "None — use /ai-channel to set one"
            lines.append(f"**Goodbye messages:** {g_status}")
            lines.append(f"**Goodbye channel:** {g_ch_str}")
            lines.append(f"**Goodbye message:** {config['goodbye_message']}")

            ai_chans = settings.get("ai_channels", [])
            if not ai_chans and not config.get("welcome_channel_id") and not config.get("goodbye_channel_id"):
                lines.append(
                    "\n⚠️ **No channels configured.** Use `/ai-channel` to set up "
                    "welcome/goodbye channels or add an AI channel as fallback."
                )
            return "\n".join(lines)

        elif fn_name == "update_server_config":
            guild  = _ctx_guild.get()
            author = _ctx_author.get()
            if guild is None or author is None:
                return "Server information is not available right now."
            perms = author.guild_permissions
            if not (perms.administrator or perms.manage_guild):
                return "❌ You need **Administrator** or **Manage Server** permission to change server settings."
            guild_id = str(guild.id)
            updates  = {}
            if "auto_roles" in fn_args:
                raw_ids   = fn_args["auto_roles"]
                validated = []
                invalid   = []
                for rid in raw_ids:
                    role = guild.get_role(int(rid)) if str(rid).isdigit() else None
                    if role:
                        validated.append(str(role.id))
                    else:
                        invalid.append(str(rid))
                if invalid:
                    return f"❌ Role IDs not found in this server: {', '.join(invalid)}. Use `get_server_roles` to list valid roles."
                updates["auto_roles"] = validated
            def _resolve_channel_by_ref(ref: str) -> tuple[str | None, str | None]:
                """Return (channel_id, error_msg). ref can be name, mention, or ID."""
                ref = ref.strip().lstrip("#").strip()
                if ref.lower() == "none":
                    return ("none", None)
                # strip mention syntax <#123>
                import re as _re
                m = _re.match(r"<#(\d+)>", ref)
                if m:
                    ref = m.group(1)
                # numeric ID
                if ref.isdigit():
                    ch = guild.get_channel(int(ref))
                    if ch is None:
                        return (None, f"No channel with ID {ref} found in this server.")
                    return (str(ch.id), None)
                # name lookup
                ref_lower = ref.lower()
                matches = [c for c in guild.text_channels if c.name.lower() == ref_lower]
                if not matches:
                    return (None, f"No text channel named '{ref}' found. Check the name and try again.")
                ch = matches[0]
                bot_member = guild.me
                if not ch.permissions_for(bot_member).send_messages:
                    return (None, f"I don't have Send Messages permission in #{ch.name}.")
                return (str(ch.id), None)

            if "welcome_channel" in fn_args:
                ch_id, err = _resolve_channel_by_ref(fn_args["welcome_channel"])
                if err:
                    return f"❌ {err}"
                updates["welcome_channel_id"] = None if ch_id == "none" else ch_id
            if "welcome_enabled" in fn_args:
                if fn_args["welcome_enabled"]:
                    config_cur  = get_server_manager_config(guild_id)
                    settings_cur = get_server_settings(guild_id)
                    if not config_cur.get("welcome_channel_id") and not settings_cur.get("ai_channels"):
                        return "❌ Please set a welcome channel first (e.g. 'set the welcome channel to #welcome') before enabling welcome messages."
                updates["welcome_enabled"] = bool(fn_args["welcome_enabled"])
            if "welcome_message" in fn_args:
                updates["welcome_message"] = str(fn_args["welcome_message"])
            if "goodbye_channel" in fn_args:
                ch_id, err = _resolve_channel_by_ref(fn_args["goodbye_channel"])
                if err:
                    return f"❌ {err}"
                updates["goodbye_channel_id"] = None if ch_id == "none" else ch_id
            if "goodbye_enabled" in fn_args:
                if fn_args["goodbye_enabled"]:
                    config_cur  = get_server_manager_config(guild_id)
                    settings_cur = get_server_settings(guild_id)
                    if not config_cur.get("goodbye_channel_id") and not settings_cur.get("ai_channels"):
                        return "❌ Please set a goodbye channel first before enabling goodbye messages."
                updates["goodbye_enabled"] = bool(fn_args["goodbye_enabled"])
            if "goodbye_message" in fn_args:
                updates["goodbye_message"] = str(fn_args["goodbye_message"])
            if not updates:
                return "No changes were specified."
            upsert_server_manager_config(guild_id, **updates)
            parts = []
            if "auto_roles" in updates:
                if updates["auto_roles"]:
                    names = [guild.get_role(int(r)).name for r in updates["auto_roles"] if guild.get_role(int(r))]
                    parts.append(f"auto-roles set to: {', '.join(names)}")
                else:
                    parts.append("auto-roles cleared")
            if "welcome_channel_id" in updates:
                if updates["welcome_channel_id"]:
                    ch = guild.get_channel(int(updates["welcome_channel_id"]))
                    parts.append(f"welcome channel set to #{ch.name if ch else updates['welcome_channel_id']}")
                else:
                    parts.append("welcome channel cleared (will use AI channel fallback)")
            if "welcome_enabled" in updates:
                parts.append(f"welcome messages {'enabled' if updates['welcome_enabled'] else 'disabled'}")
            if "welcome_message" in updates:
                parts.append("welcome message updated")
            if "goodbye_channel_id" in updates:
                if updates["goodbye_channel_id"]:
                    ch = guild.get_channel(int(updates["goodbye_channel_id"]))
                    parts.append(f"goodbye channel set to #{ch.name if ch else updates['goodbye_channel_id']}")
                else:
                    parts.append("goodbye channel cleared (will use AI channel fallback)")
            if "goodbye_enabled" in updates:
                parts.append(f"goodbye messages {'enabled' if updates['goodbye_enabled'] else 'disabled'}")
            if "goodbye_message" in updates:
                parts.append("goodbye message updated")
            return "✅ Done — " + "; ".join(parts) + "."

        elif fn_name == "web_search":
            query = fn_args.get("query", "").strip()
            if not query:
                return "No search query provided."
            from ddgs import DDGS
            loop       = asyncio.get_event_loop()
            last_exc   = None
            _BACKOFFS  = [1.0, 3.0]   # seconds between retries
            for attempt in range(3):
                try:
                    results = await loop.run_in_executor(
                        None,
                        lambda: DDGS().text(query, max_results=5),
                    )
                    if not results:
                        return f"No web results found for '{query}'."
                    lines = []
                    for r in results[:5]:
                        title = r.get("title", "")
                        body  = r.get("body", "")[:250]
                        href  = r.get("href", "")
                        lines.append(f"**{title}**\n{body}\n{href}")
                    log.info("[WEB SEARCH] query=%r  results=%d", query, len(results))
                    return "\n\n---\n".join(lines)
                except Exception as exc:
                    last_exc = exc
                    if attempt < len(_BACKOFFS):
                        log.warning(
                            "web_search attempt %d failed (%s), retrying in %.0fs…",
                            attempt + 1, exc, _BACKOFFS[attempt],
                        )
                        await asyncio.sleep(_BACKOFFS[attempt])
                    else:
                        log.error("web_search all retries exhausted: %s", exc)
            return "Web search is temporarily unavailable, please try again in a moment."

        else:
            return f"(Tool '{fn_name}' not implemented yet)"

    except Exception as exc:
        log.error("AI tool %s error: %s", fn_name, exc)
        return f"Couldn't fetch that data right now ({exc})."


# ══════════════════════════════════════════════════════════════════════════════
#  AI — on_message handler  (@mention / conversation mode / AI channels)
# ══════════════════════════════════════════════════════════════════════════════

@bot.event
async def on_message(message: discord.Message):
    # Ignore bots and DMs
    if message.author.bot:
        return
    if not message.guild:
        return

    bot_mentioned = bot.user in (message.mentions or [])
    replying_to_bot = (
        message.reference
        and message.reference.resolved
        and isinstance(message.reference.resolved, discord.Message)
        and message.reference.resolved.author == bot.user
    )

    guild_id  = str(message.guild.id)
    ch_id_str = str(message.channel.id)
    settings  = get_server_settings(guild_id)
    mode      = settings.get("interaction_mode", "mention_only")
    ai_chans  = [str(c) for c in settings.get("ai_channels", [])]
    in_ai_ch  = ch_id_str in ai_chans
    conv_live = _conv.is_active(message.channel.id)

    # ── Ambient pre-context tracking ─────────────────────────────────────────
    # Silently record every non-bot message in AI-enabled channels so that
    # when UCE IS triggered it can see what the channel was discussing before
    # it was addressed.  This is a fast SQLite write — no OpenAI call, no
    # blocking.  Only runs for configured AI channels to keep it targeted.
    if in_ai_ch:
        try:
            from ai.memory import append_channel_context
            append_channel_context(
                ch_id_str,
                message.author.display_name,
                message.content or "",
            )
        except Exception:
            pass  # never let context tracking break message handling

    # Decide whether to engage
    if mode == "silent":
        await bot.process_commands(message)
        return

    # In mention_only mode the bot ONLY responds to direct @mentions — no
    # conversation window, no reply-chain triggers.
    if mode == "mention_only":
        should_respond = bot_mentioned
    else:
        should_respond = (
            bot_mentioned
            or (mode in ("mention_replies", "community") and replying_to_bot)
            or (mode in ("ai_channel", "community") and in_ai_ch)
            or conv_live
        )

    if not should_respond:
        await bot.process_commands(message)
        return

    # Rate limit
    if not _cd.is_allowed(message.author.id, message.channel.id):
        await bot.process_commands(message)
        return

    # Strip @mention text
    content = message.content or ""
    if bot.user:
        content = (
            content
            .replace(f"<@{bot.user.id}>", "")
            .replace(f"<@!{bot.user.id}>", "")
            .strip()
        )
    if not content:
        content = "Hey!"

    # Open / refresh conversation window (only for modes that use it)
    if mode != "mention_only" and (bot_mentioned or conv_live):
        _conv.activate(message.channel.id)

    _cd.stamp(message.author.id, message.channel.id)

    if ai_brain is None:
        await message.reply("My AI brain isn't online yet — give me a second and try again. 🤖")
        await bot.process_commands(message)
        return

    # Brief pause before replying — ensures the message was meant for the bot
    # and avoids an instant "jumped in" feel.
    await asyncio.sleep(1.5)

    # Set context vars so tool executor can access guild/author
    _ctx_guild.set(message.guild)
    _ctx_author.set(message.author)

    async with message.channel.typing():
        reply = await ai_brain.process_message(
            content    = content,
            guild_id   = guild_id,
            user_id    = str(message.author.id),
            user_name  = message.author.display_name,
            channel_id = ch_id_str,
            settings   = settings,
        )

    await _dispatch_security_alerts()

    if reply:
        # Discord 2000-char limit
        chunks = [reply[i:i+2000] for i in range(0, len(reply), 2000)]
        for chunk in chunks:
            await message.reply(chunk)

    await bot.process_commands(message)


# ══════════════════════════════════════════════════════════════════════════════
#  AI — Slash commands
# ══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="ask", description="Ask Uce anything — AI-powered response")
@app_commands.describe(question="Your question or message")
async def ask(interaction: discord.Interaction, question: str):
    await interaction.response.defer()
    if ai_brain is None:
        await interaction.followup.send("My brain is still warming up — try again in a moment. 🤖")
        return
    guild_id  = str(interaction.guild_id) if interaction.guild_id else "0"
    ch_id     = str(interaction.channel_id)
    settings  = get_server_settings(guild_id)
    user_name = interaction.user.display_name

    # Set context vars so server-management tools can access guild/author
    _ctx_guild.set(interaction.guild)
    _ctx_author.set(interaction.user)

    reply = await ai_brain.process_message(
        content    = question,
        guild_id   = guild_id,
        user_id    = str(interaction.user.id),
        user_name  = user_name,
        channel_id = ch_id,
        settings   = settings,
    )
    await _dispatch_security_alerts()
    if reply:
        chunks = [reply[i:i+2000] for i in range(0, len(reply), 2000)]
        await interaction.followup.send(chunks[0])
        for chunk in chunks[1:]:
            await interaction.followup.send(chunk)
    else:
        await interaction.followup.send("Hmm, I got nothing. Try again. 🤷")


@bot.tree.command(
    name="ai-personality",
    description="Configure Uce's full personality for this server [Admin only]",
)
@app_commands.describe(
    personality     = "Core character — who Uce is in this server",
    humor           = "Humor level",
    roast           = "Roast / trash-talk level",
    confidence      = "How confident Uce sounds",
    emoji           = "Emoji usage",
    response_length = "How long responses are",
    sports_knowledge= "Depth of sports knowledge shown",
    profanity       = "Language filter",
)
@app_commands.choices(
    personality=[
        app_commands.Choice(name="🏈 Locker Room — one of the boys (default)", value="locker_room"),
        app_commands.Choice(name="📋 Coach — motivational and strategic",        value="coach"),
        app_commands.Choice(name="🔥 Trash Talker — witty and competitive",      value="trash_talker"),
        app_commands.Choice(name="😂 Meme Lord — internet humor and chaos",      value="meme_lord"),
        app_commands.Choice(name="⚖️ Commissioner — professional league manager", value="commissioner"),
    ],
    humor=[
        app_commands.Choice(name="Serious — no jokes",          value="serious"),
        app_commands.Choice(name="Balanced — light and friendly", value="balanced"),
        app_commands.Choice(name="Funny — entertaining",         value="funny"),
        app_commands.Choice(name="Chaotic — unhinged energy",    value="chaotic"),
    ],
    roast=[
        app_commands.Choice(name="Off — no roasting",             value="off"),
        app_commands.Choice(name="Light — friendly banter",       value="light"),
        app_commands.Choice(name="Medium — real burns allowed",   value="medium"),
        app_commands.Choice(name="Heavy — here for the smoke",    value="heavy"),
        app_commands.Choice(name="Savage — absolute no mercy",    value="savage"),
    ],
    confidence=[
        app_commands.Choice(name="Humble — open to being wrong",  value="humble"),
        app_commands.Choice(name="Normal — stands behind takes",  value="normal"),
        app_commands.Choice(name="Cocky — delivers takes as facts", value="cocky"),
    ],
    emoji=[
        app_commands.Choice(name="None — text only",    value="none"),
        app_commands.Choice(name="Minimal — 1 max",     value="minimal"),
        app_commands.Choice(name="Balanced — natural",  value="balanced"),
        app_commands.Choice(name="Heavy — let it flow", value="heavy"),
    ],
    response_length=[
        app_commands.Choice(name="Very Short — one sentence",   value="very_short"),
        app_commands.Choice(name="Short — 1-2 sentences",       value="short"),
        app_commands.Choice(name="Medium — 2-4 sentences",      value="medium"),
        app_commands.Choice(name="Detailed — full breakdown",   value="detailed"),
    ],
    sports_knowledge=[
        app_commands.Choice(name="Casual Fan — accessible talk",     value="casual_fan"),
        app_commands.Choice(name="Football Expert — deep knowledge", value="football_expert"),
        app_commands.Choice(name="Multi-Sport — cross-sport refs",   value="multi_sport"),
    ],
    profanity=[
        app_commands.Choice(name="Clean — no swearing",       value="clean"),
        app_commands.Choice(name="Mild — PG-13 language",     value="mild"),
        app_commands.Choice(name="Unrestricted — server default", value="server_default"),
    ],
)
async def ai_personality_cmd(
    interaction: discord.Interaction,
    personality:      str | None = None,
    humor:            str | None = None,
    roast:            str | None = None,
    confidence:       str | None = None,
    emoji:            str | None = None,
    response_length:  str | None = None,
    sports_knowledge: str | None = None,
    profanity:        str | None = None,
):
    await interaction.response.defer(ephemeral=True)
    if not interaction.guild:
        return await interaction.followup.send("This command only works inside a server.", ephemeral=True)
    perms = interaction.user.guild_permissions
    if not (perms.administrator or perms.manage_guild):
        return await interaction.followup.send(
            "You need **Administrator** or **Manage Server** permission to change AI settings.",
            ephemeral=True,
        )

    guild_id = str(interaction.guild.id)
    updates: dict = {}
    if personality:      updates["personality"]      = personality
    if humor:            updates["humor_level"]       = humor
    if roast:            updates["roast_level"]       = roast
    if confidence:       updates["confidence"]        = confidence
    if emoji:            updates["emoji_usage"]       = emoji
    if response_length:  updates["response_length"]   = response_length
    if sports_knowledge: updates["sports_knowledge"]  = sports_knowledge
    if profanity:        updates["profanity"]         = profanity

    if updates:
        upsert_server_settings(guild_id, **updates)

    s = get_server_settings(guild_id)

    _PERSONALITY_LABELS = {
        "locker_room":  "🏈 Locker Room",
        "coach":        "📋 Coach",
        "trash_talker": "🔥 Trash Talker",
        "meme_lord":    "😂 Meme Lord",
        "commissioner": "⚖️ Commissioner",
    }

    embed = discord.Embed(title="🎭 Uce Personality Settings", color=0x7A5C2E)
    embed.add_field(name="Core Personality",  value=_PERSONALITY_LABELS.get(s["personality"], s["personality"].replace("_"," ").title()), inline=False)
    embed.add_field(name="Humor",             value=s["humor_level"].replace("_"," ").title(),    inline=True)
    embed.add_field(name="Roast",             value=s["roast_level"].title(),                      inline=True)
    embed.add_field(name="Confidence",        value=s["confidence"].title(),                       inline=True)
    embed.add_field(name="Emoji",             value=s["emoji_usage"].title(),                      inline=True)
    embed.add_field(name="Response Length",   value=s["response_length"].replace("_"," ").title(), inline=True)
    embed.add_field(name="Sports Knowledge",  value=s["sports_knowledge"].replace("_"," ").title(), inline=True)
    embed.add_field(name="Profanity",         value=s["profanity"].replace("_"," ").title(),       inline=True)
    embed.add_field(name="Interaction Mode",  value=s["interaction_mode"].replace("_"," ").title(), inline=True)
    embed.set_footer(text="Uce • Personality Settings — changes apply to the next message")
    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(name="ai-settings", description="Quick-configure Uce's AI settings [Admin only]")
@app_commands.describe(
    humor="Humor level",
    roast="Roast / trash-talk level",
    emoji="Emoji usage",
    mode="How Uce participates in chat",
    response_length="How long Uce's answers are",
)
@app_commands.choices(
    humor=[
        app_commands.Choice(name="Serious — no jokes",           value="serious"),
        app_commands.Choice(name="Balanced — light and friendly", value="balanced"),
        app_commands.Choice(name="Funny — entertaining",          value="funny"),
        app_commands.Choice(name="Chaotic — unhinged energy",     value="chaotic"),
    ],
    roast=[
        app_commands.Choice(name="Off",    value="off"),
        app_commands.Choice(name="Light",  value="light"),
        app_commands.Choice(name="Medium", value="medium"),
        app_commands.Choice(name="Heavy",  value="heavy"),
        app_commands.Choice(name="Savage", value="savage"),
    ],
    emoji=[
        app_commands.Choice(name="None",     value="none"),
        app_commands.Choice(name="Minimal",  value="minimal"),
        app_commands.Choice(name="Balanced", value="balanced"),
        app_commands.Choice(name="Heavy",    value="heavy"),
    ],
    mode=[
        app_commands.Choice(name="Silent",             value="silent"),
        app_commands.Choice(name="Mention Only",       value="mention_only"),
        app_commands.Choice(name="Mention + Replies",  value="mention_replies"),
        app_commands.Choice(name="AI Channel",         value="ai_channel"),
        app_commands.Choice(name="Community Mode",     value="community"),
    ],
    response_length=[
        app_commands.Choice(name="Very Short",  value="very_short"),
        app_commands.Choice(name="Short",       value="short"),
        app_commands.Choice(name="Medium",      value="medium"),
        app_commands.Choice(name="Detailed",    value="detailed"),
    ],
)
async def ai_settings(
    interaction: discord.Interaction,
    humor:           str | None = None,
    roast:           str | None = None,
    emoji:           str | None = None,
    mode:            str | None = None,
    response_length: str | None = None,
):
    await interaction.response.defer(ephemeral=True)
    if not interaction.guild:
        return await interaction.followup.send("This command only works inside a server.", ephemeral=True)
    perms = interaction.user.guild_permissions
    if not (perms.administrator or perms.manage_guild):
        return await interaction.followup.send(
            "You need **Administrator** or **Manage Server** permission to change AI settings.",
            ephemeral=True,
        )

    guild_id = str(interaction.guild.id)
    updates: dict = {}
    if humor:           updates["humor_level"]      = humor
    if roast:           updates["roast_level"]      = roast
    if emoji:           updates["emoji_usage"]      = emoji
    if mode:            updates["interaction_mode"] = mode
    if response_length: updates["response_length"]  = response_length

    if updates:
        upsert_server_settings(guild_id, **updates)

    s = get_server_settings(guild_id)
    embed = discord.Embed(title="🤖 Uce AI Settings", color=0x7A5C2E)
    embed.add_field(name="Humor Level",      value=s["humor_level"].replace("_"," ").title(),      inline=True)
    embed.add_field(name="Roast Level",      value=s["roast_level"].title(),                        inline=True)
    embed.add_field(name="Emoji Usage",      value=s["emoji_usage"].title(),                        inline=True)
    embed.add_field(name="Interaction Mode", value=s["interaction_mode"].replace("_"," ").title(), inline=True)
    embed.add_field(name="Response Length",  value=s["response_length"].replace("_"," ").title(),  inline=True)
    ai_chs = s.get("ai_channels", [])
    ch_mentions = " ".join(f"<#{c}>" for c in ai_chs) if ai_chs else "None"
    embed.add_field(name="AI Channels", value=ch_mentions, inline=False)
    embed.set_footer(text="Uce • AI Settings — use /ai-personality for full control")
    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(
    name="ai-channel",
    description="Configure AI channels and welcome/goodbye settings [Admin only]",
)
@app_commands.describe(
    action="What to configure",
    channel="Channel to use (required for channel-setting actions)",
)
@app_commands.choices(action=[
    app_commands.Choice(name="Add AI channel",            value="add"),
    app_commands.Choice(name="Remove AI channel",         value="remove"),
    app_commands.Choice(name="Set welcome channel",       value="welcome-channel"),
    app_commands.Choice(name="Set goodbye channel",       value="goodbye-channel"),
    app_commands.Choice(name="Enable welcome messages",   value="welcome-on"),
    app_commands.Choice(name="Disable welcome messages",  value="welcome-off"),
    app_commands.Choice(name="Enable goodbye messages",   value="goodbye-on"),
    app_commands.Choice(name="Disable goodbye messages",  value="goodbye-off"),
    app_commands.Choice(name="Preview welcome message",   value="preview-welcome"),
    app_commands.Choice(name="Preview goodbye message",   value="preview-goodbye"),
    app_commands.Choice(name="View all channel settings", value="view"),
])
async def ai_channel(
    interaction: discord.Interaction,
    action:  str,
    channel: discord.TextChannel | None = None,
):
    await interaction.response.defer(ephemeral=True)

    if not interaction.guild:
        await interaction.followup.send(
            "This command only works inside a server.", ephemeral=True
        )
        return

    perms = interaction.user.guild_permissions
    if not (perms.administrator or perms.manage_guild):
        await interaction.followup.send(
            "You need **Administrator** or **Manage Server** permission to use this command.",
            ephemeral=True,
        )
        return

    guild_id = str(interaction.guild.id)

    # ── view ────────────────────────────────────────────────────────────────
    if action == "view":
        settings = get_server_settings(guild_id)
        chans    = settings.get("ai_channels", [])
        config   = get_server_manager_config(guild_id)

        ai_ch_list = ", ".join(f"<#{c}>" for c in chans) if chans else "None"

        def _ch_str(ch_id):
            if not ch_id:
                return "Not set (falls back to first AI channel)"
            ch = interaction.guild.get_channel(int(ch_id))
            return ch.mention if ch else f"⚠️ Deleted channel (ID: {ch_id})"

        w_status = "✅ Enabled"  if config["welcome_enabled"] else "❌ Disabled"
        g_status = "✅ Enabled"  if config["goodbye_enabled"] else "❌ Disabled"

        embed = discord.Embed(title="📋 Channel & Greeting Settings", color=0x1E90FF)
        embed.add_field(name="AI Channels", value=ai_ch_list, inline=False)
        embed.add_field(
            name="👋 Welcome",
            value=(
                f"Status: {w_status}\n"
                f"Channel: {_ch_str(config['welcome_channel_id'])}\n"
                f"Message: {config['welcome_message'][:80]}{'…' if len(config['welcome_message']) > 80 else ''}"
            ),
            inline=False,
        )
        embed.add_field(
            name="👋 Goodbye",
            value=(
                f"Status: {g_status}\n"
                f"Channel: {_ch_str(config['goodbye_channel_id'])}\n"
                f"Message: {config['goodbye_message'][:80]}{'…' if len(config['goodbye_message']) > 80 else ''}"
            ),
            inline=False,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    # ── add / remove AI channel ──────────────────────────────────────────────
    if action in ("add", "remove"):
        if channel is None:
            await interaction.followup.send(
                "Please specify a **channel** for this action.", ephemeral=True
            )
            return
        settings = get_server_settings(guild_id)
        chans    = [str(c) for c in settings.get("ai_channels", [])]
        cid      = str(channel.id)
        if action == "add":
            if cid not in chans:
                chans.append(cid)
            msg = f"✅ {channel.mention} added as an AI channel. Uce will reply to all messages there."
        else:
            chans = [c for c in chans if c != cid]
            msg   = f"✅ {channel.mention} removed from AI channels."
        upsert_server_settings(guild_id, ai_channels=chans)
        await interaction.followup.send(msg, ephemeral=True)
        return

    # ── welcome-channel / goodbye-channel ────────────────────────────────────
    if action in ("welcome-channel", "goodbye-channel"):
        if channel is None:
            await interaction.followup.send(
                "Please specify a **channel** for this action.", ephemeral=True
            )
            return
        bot_perms = channel.permissions_for(interaction.guild.me)
        if not bot_perms.send_messages:
            await interaction.followup.send(
                f"❌ I don't have **Send Messages** permission in {channel.mention}. "
                "Fix my channel permissions first.",
                ephemeral=True,
            )
            return
        label     = "welcome" if action == "welcome-channel" else "goodbye"
        db_key    = f"{label}_channel_id"
        upsert_server_manager_config(guild_id, **{db_key: str(channel.id)})
        await interaction.followup.send(
            f"✅ {label.capitalize()} messages will now be posted to {channel.mention}.",
            ephemeral=True,
        )
        return

    # ── enable / disable welcome ─────────────────────────────────────────────
    if action in ("welcome-on", "welcome-off"):
        enabled = action == "welcome-on"
        if enabled:
            config = get_server_manager_config(guild_id)
            settings = get_server_settings(guild_id)
            if not config.get("welcome_channel_id") and not settings.get("ai_channels"):
                await interaction.followup.send(
                    "⚠️ No welcome channel is set. Use **Set welcome channel** or "
                    "add an AI channel first so messages have somewhere to go.",
                    ephemeral=True,
                )
                return
        upsert_server_manager_config(guild_id, welcome_enabled=enabled)
        status = "✅ enabled" if enabled else "❌ disabled"
        await interaction.followup.send(
            f"Welcome messages are now **{status}**.", ephemeral=True
        )
        return

    # ── enable / disable goodbye ─────────────────────────────────────────────
    if action in ("goodbye-on", "goodbye-off"):
        enabled = action == "goodbye-on"
        if enabled:
            config = get_server_manager_config(guild_id)
            settings = get_server_settings(guild_id)
            if not config.get("goodbye_channel_id") and not settings.get("ai_channels"):
                await interaction.followup.send(
                    "⚠️ No goodbye channel is set. Use **Set goodbye channel** or "
                    "add an AI channel first so messages have somewhere to go.",
                    ephemeral=True,
                )
                return
        upsert_server_manager_config(guild_id, goodbye_enabled=enabled)
        status = "✅ enabled" if enabled else "❌ disabled"
        await interaction.followup.send(
            f"Goodbye messages are now **{status}**.", ephemeral=True
        )
        return

    # ── preview welcome ──────────────────────────────────────────────────────
    if action == "preview-welcome":
        config = get_server_manager_config(guild_id)
        preview = (
            config["welcome_message"]
            .replace("{user}", interaction.user.mention)
            .replace("{server}", interaction.guild.name)
            .replace("{memberCount}", str(interaction.guild.member_count or "?"))
        )
        ch_id  = config.get("welcome_channel_id")
        ch_str = f"<#{ch_id}>" if ch_id else "first AI channel (fallback)"
        await interaction.followup.send(
            f"**Welcome message preview** (posts to {ch_str}):\n\n{preview}",
            ephemeral=True,
        )
        return

    # ── preview goodbye ──────────────────────────────────────────────────────
    if action == "preview-goodbye":
        config = get_server_manager_config(guild_id)
        preview = (
            config["goodbye_message"]
            .replace("{user}", interaction.user.display_name)
            .replace("{server}", interaction.guild.name)
            .replace("{memberCount}", str(interaction.guild.member_count or "?"))
        )
        ch_id  = config.get("goodbye_channel_id")
        ch_str = f"<#{ch_id}>" if ch_id else "first AI channel (fallback)"
        await interaction.followup.send(
            f"**Goodbye message preview** (posts to {ch_str}):\n\n{preview}",
            ephemeral=True,
        )
        return


@bot.tree.command(
    name="set-welcome-channel",
    description="Set the channel where welcome messages are posted [Admin only]",
)
@app_commands.describe(channel="Channel for welcome messages")
async def set_welcome_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    await interaction.response.defer(ephemeral=True)
    if not interaction.guild:
        return await interaction.followup.send("This command only works inside a server.", ephemeral=True)
    perms = interaction.user.guild_permissions
    if not (perms.administrator or perms.manage_guild):
        return await interaction.followup.send("You need **Administrator** or **Manage Server** permission.", ephemeral=True)
    bot_perms = channel.permissions_for(interaction.guild.me)
    if not bot_perms.send_messages:
        return await interaction.followup.send(f"❌ I don't have **Send Messages** permission in {channel.mention}.", ephemeral=True)
    upsert_server_manager_config(str(interaction.guild.id), welcome_channel_id=str(channel.id))
    await interaction.followup.send(f"✅ Welcome messages will now be posted to {channel.mention}.", ephemeral=True)


@bot.tree.command(
    name="set-goodbye-channel",
    description="Set the channel where goodbye messages are posted [Admin only]",
)
@app_commands.describe(channel="Channel for goodbye messages")
async def set_goodbye_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    await interaction.response.defer(ephemeral=True)
    if not interaction.guild:
        return await interaction.followup.send("This command only works inside a server.", ephemeral=True)
    perms = interaction.user.guild_permissions
    if not (perms.administrator or perms.manage_guild):
        return await interaction.followup.send("You need **Administrator** or **Manage Server** permission.", ephemeral=True)
    bot_perms = channel.permissions_for(interaction.guild.me)
    if not bot_perms.send_messages:
        return await interaction.followup.send(f"❌ I don't have **Send Messages** permission in {channel.mention}.", ephemeral=True)
    upsert_server_manager_config(str(interaction.guild.id), goodbye_channel_id=str(channel.id))
    await interaction.followup.send(f"✅ Goodbye messages will now be posted to {channel.mention}.", ephemeral=True)


@bot.tree.command(
    name="set-welcome-message",
    description="Save a custom welcome message template [Admin only]",
)
@app_commands.describe(message="Custom welcome message. Supports {mention} {user} {username} {server} {membercount}")
async def set_welcome_message(interaction: discord.Interaction, message: str):
    await interaction.response.defer(ephemeral=True)
    if not interaction.guild:
        return await interaction.followup.send("This command only works inside a server.", ephemeral=True)
    perms = interaction.user.guild_permissions
    if not (perms.administrator or perms.manage_guild):
        return await interaction.followup.send("You need **Administrator** or **Manage Server** permission.", ephemeral=True)
    upsert_server_manager_config(str(interaction.guild.id), welcome_message=message)
    await interaction.followup.send(
        f"✅ Custom welcome message saved.\n\n**Preview:**\n{message[:200]}",
        ephemeral=True,
    )


@bot.tree.command(
    name="set-goodbye-message",
    description="Save a custom goodbye message template [Admin only]",
)
@app_commands.describe(message="Custom goodbye message. Supports {user} {username} {server} {membercount}")
async def set_goodbye_message(interaction: discord.Interaction, message: str):
    await interaction.response.defer(ephemeral=True)
    if not interaction.guild:
        return await interaction.followup.send("This command only works inside a server.", ephemeral=True)
    perms = interaction.user.guild_permissions
    if not (perms.administrator or perms.manage_guild):
        return await interaction.followup.send("You need **Administrator** or **Manage Server** permission.", ephemeral=True)
    upsert_server_manager_config(str(interaction.guild.id), goodbye_message=message)
    await interaction.followup.send(
        f"✅ Custom goodbye message saved.\n\n**Preview:**\n{message[:200]}",
        ephemeral=True,
    )


@bot.tree.command(
    name="welcome-mode",
    description="Choose how welcome messages are generated — AI or Custom [Admin only]",
)
@app_commands.describe(mode="AI uses OpenAI to write a unique message each time; Custom uses your saved template")
@app_commands.choices(mode=[
    app_commands.Choice(name="AI — Uce writes a unique message each time", value="ai"),
    app_commands.Choice(name="Custom — use my saved template",              value="custom"),
])
async def welcome_mode_cmd(interaction: discord.Interaction, mode: str):
    await interaction.response.defer(ephemeral=True)
    if not interaction.guild:
        return await interaction.followup.send("This command only works inside a server.", ephemeral=True)
    perms = interaction.user.guild_permissions
    if not (perms.administrator or perms.manage_guild):
        return await interaction.followup.send("You need **Administrator** or **Manage Server** permission.", ephemeral=True)
    upsert_server_manager_config(str(interaction.guild.id), welcome_mode=mode)
    label = "🤖 AI-generated" if mode == "ai" else "✏️ Custom template"
    await interaction.followup.send(f"✅ Welcome messages will now use **{label}** mode.", ephemeral=True)


@bot.tree.command(
    name="goodbye-mode",
    description="Choose how goodbye messages are generated — AI or Custom [Admin only]",
)
@app_commands.describe(mode="AI uses OpenAI to write a unique message each time; Custom uses your saved template")
@app_commands.choices(mode=[
    app_commands.Choice(name="AI — Uce writes a unique message each time", value="ai"),
    app_commands.Choice(name="Custom — use my saved template",              value="custom"),
])
async def goodbye_mode_cmd(interaction: discord.Interaction, mode: str):
    await interaction.response.defer(ephemeral=True)
    if not interaction.guild:
        return await interaction.followup.send("This command only works inside a server.", ephemeral=True)
    perms = interaction.user.guild_permissions
    if not (perms.administrator or perms.manage_guild):
        return await interaction.followup.send("You need **Administrator** or **Manage Server** permission.", ephemeral=True)
    upsert_server_manager_config(str(interaction.guild.id), goodbye_mode=mode)
    label = "🤖 AI-generated" if mode == "ai" else "✏️ Custom template"
    await interaction.followup.send(f"✅ Goodbye messages will now use **{label}** mode.", ephemeral=True)


@bot.tree.command(
    name="welcome",
    description="Manually send a welcome message for a member [Admin only]",
)
@app_commands.describe(member="The member to welcome")
async def welcome_cmd(interaction: discord.Interaction, member: discord.Member):
    await interaction.response.defer(ephemeral=True)
    if not interaction.guild:
        return await interaction.followup.send("This command only works inside a server.", ephemeral=True)
    perms = interaction.user.guild_permissions
    if not (perms.administrator or perms.manage_guild):
        return await interaction.followup.send("You need **Administrator** or **Manage Server** permission.", ephemeral=True)
    await handle_member_join(member, ai_brain=ai_brain)
    await interaction.followup.send(f"✅ Welcome message sent for {member.mention}.", ephemeral=True)


@bot.tree.command(
    name="goodbye",
    description="Manually send a goodbye message for a member [Admin only]",
)
@app_commands.describe(member="The member to say goodbye to")
async def goodbye_cmd(interaction: discord.Interaction, member: discord.Member):
    await interaction.response.defer(ephemeral=True)
    if not interaction.guild:
        return await interaction.followup.send("This command only works inside a server.", ephemeral=True)
    perms = interaction.user.guild_permissions
    if not (perms.administrator or perms.manage_guild):
        return await interaction.followup.send("You need **Administrator** or **Manage Server** permission.", ephemeral=True)
    await handle_member_remove(member, ai_brain=ai_brain)
    await interaction.followup.send(f"✅ Goodbye message sent for **{member.display_name}**.", ephemeral=True)


@bot.tree.command(name="morning-checkin", description="Configure Uce's daily morning check-in message")
@app_commands.describe(
    enabled  = "Turn the morning check-in on or off",
    hour     = "Hour to post (0-23, 24h format)",
    minute   = "Minute to post (0-59)",
    timezone = "Timezone, e.g. America/New_York",
    channel  = "Channel to post in",
)
async def morning_checkin(
    interaction: discord.Interaction,
    enabled:  bool,
    channel:  discord.TextChannel | None = None,
    hour:     int | None = None,
    minute:   int | None = None,
    timezone: str = "America/New_York",
):
    await interaction.response.defer(ephemeral=True)
    guild_id = str(interaction.guild_id)
    settings = get_server_settings(guild_id)
    cfg      = settings.get("morning_checkin") or {}

    cfg["enabled"] = enabled
    if channel:  cfg["channel_id"] = str(channel.id)
    if hour   is not None: cfg["time"] = f"{hour:02d}:{(minute or 0):02d}"
    if timezone: cfg["timezone"] = timezone

    upsert_server_settings(guild_id, morning_checkin=cfg)
    status = "✅ enabled" if enabled else "⛔ disabled"
    time_str = cfg.get("time", "08:00")
    ch_str   = f"<#{cfg['channel_id']}>" if cfg.get("channel_id") else "not set"
    await interaction.followup.send(
        f"Morning check-in {status}  •  **{time_str}** {cfg.get('timezone','ET')}  •  channel: {ch_str}",
        ephemeral=True,
    )


@bot.tree.command(name="night-checkin", description="Configure Uce's daily night check-in message")
@app_commands.describe(
    enabled  = "Turn the night check-in on or off",
    hour     = "Hour to post (0-23, 24h format)",
    minute   = "Minute to post (0-59)",
    timezone = "Timezone, e.g. America/New_York",
    channel  = "Channel to post in",
)
async def night_checkin(
    interaction: discord.Interaction,
    enabled:  bool,
    channel:  discord.TextChannel | None = None,
    hour:     int | None = None,
    minute:   int | None = None,
    timezone: str = "America/New_York",
):
    await interaction.response.defer(ephemeral=True)
    guild_id = str(interaction.guild_id)
    settings = get_server_settings(guild_id)
    cfg      = settings.get("night_checkin") or {}

    cfg["enabled"] = enabled
    if channel:  cfg["channel_id"] = str(channel.id)
    if hour   is not None: cfg["time"] = f"{hour:02d}:{(minute or 0):02d}"
    if timezone: cfg["timezone"] = timezone

    upsert_server_settings(guild_id, night_checkin=cfg)
    status = "✅ enabled" if enabled else "⛔ disabled"
    time_str = cfg.get("time", "21:00")
    ch_str   = f"<#{cfg['channel_id']}>" if cfg.get("channel_id") else "not set"
    await interaction.followup.send(
        f"Night check-in {status}  •  **{time_str}** {cfg.get('timezone','ET')}  •  channel: {ch_str}",
        ephemeral=True,
    )


# ── Check-in loop (runs every minute) ────────────────────────────────────────
@tasks.loop(minutes=1)
async def checkin_loop():
    if ai_brain is None:
        return
    try:
        _conv.cleanup()
        await run_checkins(bot, ai_brain, get_server_settings, recall_server)
    except Exception as exc:
        log.error("checkin_loop error: %s", exc)




@bot.event
async def on_ready():
    global session, ai_brain

    if session is None:
        session = aiohttp.ClientSession()

    # Initialise SQLite tables
    try:
        init_db()
        init_server_manager_db()
        init_announcements_db()
        print("Database initialised.")
    except Exception as e:
        print(f"Database init error: {e}")

    # Build AI brain
    if ai_brain is None:
        ai_brain = AIBrain(tools_executor=_ai_tools_executor)
        status = "online ✅" if ai_brain.available else "offline (no OPENAI_API_KEY) ⚠️"
        print(f"AI brain {status}")

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

    if not checkin_loop.is_running():
        checkin_loop.start()

    if not announcements_loop.is_running():
        announcements_loop.start()

    from datetime import datetime, timezone as _tz
    _now = datetime.now(_tz.utc)
    print(
        f"Date context: {_now.strftime('%A, %B %d, %Y')} UTC  "
        f"(year={_now.year}  epoch={int(_now.timestamp())})"
    )
    print(f"BOT READY - Logged in as {bot.user}")


# ══════════════════════════════════════════════════════════════════════════════
#  Server Manager — member join / leave events
# ══════════════════════════════════════════════════════════════════════════════

@bot.event
async def on_member_join(member: discord.Member):
    """Auto-assign roles and post welcome messages when a member joins."""
    print(f"Member joined: {member.name} (guild: {member.guild.name})")
    try:
        await handle_member_join(member, ai_brain=ai_brain)
    except Exception as exc:
        log.error("on_member_join error guild=%s: %s", member.guild.id, exc)


@bot.event
async def on_member_remove(member: discord.Member):
    """Post goodbye messages when a member leaves."""
    print(f"Member left: {member.name} (guild: {member.guild.name})")
    try:
        await handle_member_remove(member, ai_brain=ai_brain)
    except Exception as exc:
        log.error("on_member_remove error guild=%s: %s", member.guild.id, exc)


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
<title>Uce — Terms of Service</title>
<style>
  body{font-family:system-ui,sans-serif;max-width:760px;margin:40px auto;padding:0 24px;color:#1a1a1a;line-height:1.7}
  h1{color:#7A5C2E}h2{color:#333;margin-top:2em}
  footer{margin-top:3em;font-size:.85em;color:#888}
</style>
</head>
<body>
<h1>🏈 Uce — Terms of Service</h1>
<p><strong>Last updated: July 2025</strong></p>

<h2>1. Acceptance</h2>
<p>By adding Uce to your Discord server or using any of its commands, you agree to these Terms of Service. If you do not agree, do not use the bot.</p>

<h2>2. Description of Service</h2>
<p>Uce provides NFL-related information including live scores, player statistics, trade headlines, and league leaders. All data is sourced from publicly available APIs (primarily ESPN). The bot does not guarantee the accuracy, completeness, or timeliness of any information provided.</p>

<h2>3. Acceptable Use</h2>
<p>You agree not to:</p>
<ul>
  <li>Use the bot for any unlawful purpose</li>
  <li>Attempt to exploit, abuse, or disrupt the bot or its hosting infrastructure</li>
  <li>Use the bot to harass or harm others</li>
  <li>Reverse engineer or attempt to extract source code through the bot's interface</li>
</ul>

<h2>4. Data &amp; Privacy</h2>
<p>Uce does not collect, store, or share personal data about users. Commands are processed in real time and no message content or user identifiers are retained. See our <a href="/privacy">Privacy Policy</a> for details.</p>

<h2>5. Disclaimer of Warranties</h2>
<p>The bot is provided "as is" without warranty of any kind. We make no guarantees regarding uptime, data accuracy, or fitness for a particular purpose. NFL statistics and news are provided for informational purposes only.</p>

<h2>6. Limitation of Liability</h2>
<p>The creators of Uce are not liable for any direct, indirect, incidental, or consequential damages arising from your use of the bot.</p>

<h2>7. Changes to Terms</h2>
<p>These terms may be updated at any time. Continued use of the bot after changes constitutes acceptance of the revised terms.</p>

<h2>8. Contact</h2>
<p>For questions or concerns, please reach out through your Discord server's administration.</p>

<footer>Uce &mdash; Unofficial. Not affiliated with the NFL or ESPN.</footer>
</body>
</html>"""

PRIVACY_HTML = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Uce — Privacy Policy</title>
<style>
  body{font-family:system-ui,sans-serif;max-width:760px;margin:40px auto;padding:0 24px;color:#1a1a1a;line-height:1.7}
  h1{color:#7A5C2E}h2{color:#333;margin-top:2em}
  footer{margin-top:3em;font-size:.85em;color:#888}
</style>
</head>
<body>
<h1>🏈 Uce — Privacy Policy</h1>
<p><strong>Last updated: July 2025</strong></p>

<h2>1. Information We Collect</h2>
<p>Uce does <strong>not</strong> collect or store any personal information. Specifically:</p>
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

<footer>Uce &mdash; Unofficial. Not affiliated with the NFL or ESPN.</footer>
</body>
</html>"""


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Uce — Dashboard</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Segoe UI',system-ui,sans-serif;background:#0d0d0d;color:#e0e0e0;min-height:100vh}
  header{background:linear-gradient(135deg,#1a1a1a 0%,#2a1f0e 100%);border-bottom:2px solid #7A5C2E;padding:20px 32px;display:flex;align-items:center;gap:16px;flex-wrap:wrap}
  header .logo{font-size:2rem}
  header h1{font-size:1.6rem;color:#e8c97a;font-weight:700;letter-spacing:.5px}
  header p{font-size:.85rem;color:#999;margin-top:2px}
  .invite-btn{margin-left:auto;background:linear-gradient(135deg,#5865F2,#4752c4);color:#fff;border:none;padding:11px 22px;border-radius:8px;font-size:.95rem;font-weight:600;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;gap:8px;transition:opacity .2s}
  .invite-btn:hover{opacity:.85}
  main{max-width:1100px;margin:0 auto;padding:28px 24px;display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:20px}
  .card{background:#1a1a1a;border:1px solid #2a2a2a;border-radius:12px;padding:22px 24px}
  .card h2{font-size:.75rem;text-transform:uppercase;letter-spacing:1.2px;color:#7A5C2E;margin-bottom:14px;font-weight:600}
  .stat{font-size:2.2rem;font-weight:700;color:#e8c97a;line-height:1}
  .stat-label{font-size:.8rem;color:#777;margin-top:6px}
  .status-dot{display:inline-block;width:10px;height:10px;border-radius:50%;background:#57F287;margin-right:7px;box-shadow:0 0 6px #57F287}
  .status-dot.offline{background:#ED4245;box-shadow:0 0 6px #ED4245}
  .status-row{display:flex;align-items:center;font-size:1rem;font-weight:600;color:#57F287}
  .status-row.offline{color:#ED4245}
  .cmd-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:4px}
  .cmd{background:#111;border:1px solid #2a2a2a;border-radius:6px;padding:7px 10px;font-size:.8rem;color:#c9a84c;font-family:monospace}
  .news-ch{font-size:1rem;color:#e8c97a;font-weight:600;word-break:break-all;margin-top:4px}
  .news-ch.none{color:#555;font-style:italic;font-size:.9rem}
  .sources{display:flex;flex-direction:column;gap:6px;margin-top:4px}
  .source-tag{background:#111;border:1px solid #2a2a2a;border-radius:6px;padding:6px 10px;font-size:.82rem;color:#aaa;display:flex;align-items:center;gap:8px}
  .source-dot{width:7px;height:7px;border-radius:50%;background:#57F287;flex-shrink:0}
  .wide{grid-column:1/-1}
  footer{text-align:center;padding:20px;font-size:.78rem;color:#444;border-top:1px solid #1a1a1a}
  footer a{color:#7A5C2E;text-decoration:none}footer a:hover{text-decoration:underline}
  @media(max-width:520px){header{padding:16px;gap:10px}.invite-btn{margin-left:0;width:100%;justify-content:center}}
</style>
</head>
<body>
<header>
  <span class="logo">🏈</span>
  <div>
    <h1>Uce</h1>
    <p>Live NFL scores, news, stats &amp; more</p>
  </div>
  <a class="invite-btn" id="inviteBtn" href="/invite" target="_blank">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M20.317 4.37a19.791 19.791 0 00-4.885-1.515.074.074 0 00-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 00-5.487 0 12.64 12.64 0 00-.617-1.25.077.077 0 00-.079-.037A19.736 19.736 0 003.677 4.37a.07.07 0 00-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 00.031.057 19.9 19.9 0 005.993 3.03.078.078 0 00.084-.028c.462-.63.874-1.295 1.226-1.994a.076.076 0 00-.041-.106 13.107 13.107 0 01-1.872-.892.077.077 0 01-.008-.128 10.2 10.2 0 00.372-.292.074.074 0 01.077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 01.078.01c.12.098.246.198.373.292a.077.077 0 01-.006.127 12.299 12.299 0 01-1.873.892.077.077 0 00-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 00.084.028 19.839 19.839 0 006.002-3.03.077.077 0 00.032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 00-.031-.03z"/></svg>
    Add to Discord
  </a>
</header>

<main>
  <!-- Status -->
  <div class="card">
    <h2>Bot Status</h2>
    <div id="statusRow" class="status-row"><span class="status-dot" id="statusDot"></span><span id="statusText">Checking...</span></div>
    <div class="stat-label" style="margin-top:10px">Latency: <span id="latency" style="color:#e8c97a">—</span></div>
  </div>

  <!-- Servers -->
  <div class="card">
    <h2>Servers</h2>
    <div class="stat" id="guildCount">—</div>
    <div class="stat-label">Discord servers using this bot</div>
  </div>

  <!-- Uptime -->
  <div class="card">
    <h2>Uptime</h2>
    <div class="stat" id="uptime">—</div>
    <div class="stat-label">Since last restart</div>
  </div>

  <!-- News channel -->
  <div class="card">
    <h2>News Channel</h2>
    <div id="newsChannel" class="news-ch none">Not configured</div>
    <div class="stat-label" style="margin-top:8px">Auto-post destination</div>
  </div>

  <!-- News sources -->
  <div class="card">
    <h2>News Sources</h2>
    <div class="sources">
      <div class="source-tag"><span class="source-dot"></span>ESPN API</div>
      <div class="source-tag"><span class="source-dot"></span>Pro Football Talk (RSS)</div>
      <div class="source-tag"><span class="source-dot"></span>Yahoo Sports (RSS)</div>
    </div>
  </div>

  <!-- Commands -->
  <div class="card wide">
    <h2>Available Commands</h2>
    <div class="cmd-grid">
      <div class="cmd">/scoreboard</div>
      <div class="cmd">/gamestats</div>
      <div class="cmd">/playerstats</div>
      <div class="cmd">/gamelog</div>
      <div class="cmd">/seasonstats</div>
      <div class="cmd">/schedule</div>
      <div class="cmd">/nfl-leaders</div>
      <div class="cmd">/headlines</div>
      <div class="cmd">/tradetracker</div>
      <div class="cmd">/nflwatch</div>
      <div class="cmd">/create-channel</div>
      <div class="cmd">/delete-channel</div>
      <div class="cmd">/rename-server</div>
      <div class="cmd">/create-category</div>
    </div>
  </div>
</main>

<footer>
  <a href="/tos">Terms of Service</a> &nbsp;·&nbsp; <a href="/privacy">Privacy Policy</a>
  &nbsp;·&nbsp; Uce — Unofficial. Not affiliated with the NFL or ESPN.
</footer>

<script>
async function refresh() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    const dot = document.getElementById('statusDot');
    const row = document.getElementById('statusRow');
    const txt = document.getElementById('statusText');
    if (d.online) {
      dot.className = 'status-dot';
      row.className = 'status-row';
      txt.textContent = 'Online';
    } else {
      dot.className = 'status-dot offline';
      row.className = 'status-row offline';
      txt.textContent = 'Offline';
    }
    document.getElementById('latency').textContent = d.latency_ms != null ? d.latency_ms + ' ms' : '—';
    document.getElementById('guildCount').textContent = d.guild_count ?? '—';
    document.getElementById('uptime').textContent = d.uptime ?? '—';
    const nc = document.getElementById('newsChannel');
    if (d.news_channel) {
      nc.textContent = d.news_channel;
      nc.className = 'news-ch';
    } else {
      nc.textContent = 'Not configured';
      nc.className = 'news-ch none';
    }
  } catch(e) {}
}
refresh();
setInterval(refresh, 15000);
</script>
</body>
</html>"""


_start_time = datetime.now(timezone.utc)

# ── Per-IP rate limiter ────────────────────────────────────────────────────────
# Reads TRUSTED_PROXY_IP from env. When set and the direct TCP peer matches,
# the leftmost X-Forwarded-For value is used as the real client IP.
# Without it, X-Forwarded-For is ignored entirely (prevents spoofing bypass).
_TRUSTED_PROXY_IP: str | None = os.getenv("TRUSTED_PROXY_IP", "").strip() or None


class _IPRateLimiter:
    """
    Sliding-window per-IP rate limiter for the aiohttp web server.

    Algorithm: sliding window counter — for each IP, keep a list of monotonic
    timestamps of recent requests. On each request, trim entries older than
    `window_secs`, then reject if the remaining count >= `max_reqs`.

    Memory: expired timestamps are removed per-request; empty IP buckets are
    swept every `window_secs` seconds so the dict never grows without bound.
    """

    def __init__(
        self,
        max_reqs: int = 60,
        window_secs: float = 60.0,
        trusted_proxy_ip: str | None = None,
    ) -> None:
        self.max_reqs = max_reqs
        self.window_secs = window_secs
        self.trusted_proxy_ip = trusted_proxy_ip
        self._store: dict[str, list[float]] = {}
        self._last_sweep: float = 0.0

    def _resolve_ip(self, request: aiohttp_web.Request) -> str:
        """
        Return the client IP to use for rate-limiting.

        X-Forwarded-For is ONLY trusted when:
          - `trusted_proxy_ip` is configured, AND
          - the direct TCP peer (`request.remote`) matches that trusted proxy.
        Otherwise the direct TCP peer is used unconditionally.
        """
        peer = request.remote or "unknown"
        if self.trusted_proxy_ip and peer == self.trusted_proxy_ip:
            xff = request.headers.get("X-Forwarded-For", "").strip()
            if xff:
                # Single trusted-proxy level: leftmost entry is the real client.
                return xff.split(",")[0].strip()
        return peer

    def check(self, ip: str) -> tuple[bool, int]:
        """
        Returns (allowed, retry_after_seconds).
        Records this request if allowed; always trims expired entries.
        """
        now = time.monotonic()
        window_start = now - self.window_secs

        bucket = self._store.setdefault(ip, [])

        # Trim expired entries — bucket is always insertion-ordered (monotonically
        # increasing timestamps), so a prefix-slice is sufficient.
        cutoff = next(
            (i for i, t in enumerate(bucket) if t > window_start),
            len(bucket),
        )
        del bucket[:cutoff]

        if len(bucket) >= self.max_reqs:
            retry_after = int(self.window_secs - (now - bucket[0])) + 1
            return False, retry_after

        bucket.append(now)

        # Periodic sweep: trim expired entries from ALL buckets, then remove
        # empty ones.  Running this on every request would be O(n_ips) — instead
        # we amortise it by running at most once per window period.
        if now - self._last_sweep > self.window_secs:
            self._last_sweep = now
            dead: list[str] = []
            for k, v in self._store.items():
                exp = next(
                    (i for i, t in enumerate(v) if t > window_start),
                    len(v),
                )
                del v[:exp]
                if not v:
                    dead.append(k)
            for k in dead:
                del self._store[k]

        return True, 0


_rate_limiter = _IPRateLimiter(
    max_reqs=60,
    window_secs=60.0,
    trusted_proxy_ip=_TRUSTED_PROXY_IP,
)


@aiohttp_web.middleware
async def _rate_limit_middleware(request: aiohttp_web.Request, handler):
    """
    Rate-limiting middleware — runs before all other middleware.
    Returns HTTP 429 with a Retry-After header when the per-IP limit is exceeded.
    Logs only the client IP (no path, headers, or body) to avoid sensitive data exposure.
    """
    import json as _j
    ip = _rate_limiter._resolve_ip(request)
    allowed, retry_after = _rate_limiter.check(ip)
    if not allowed:
        log.warning("Rate limit exceeded ip=%s", ip)
        return aiohttp_web.Response(
            text=_j.dumps({"error": "Too many requests", "retry_after": retry_after}),
            status=429,
            content_type="application/json",
            headers={"Retry-After": str(retry_after)},
        )
    return await handler(request)


# ── Security headers added to every HTML response ─────────────────────────────
_HTML_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options":        "DENY",
    # Allows inline styles/scripts (used by the dashboard) and same-origin fetches.
    "Content-Security-Policy": "default-src 'self' 'unsafe-inline'; connect-src 'self'",
}


@aiohttp_web.middleware
async def _security_middleware(request: aiohttp_web.Request, handler):
    """
    Web-server security middleware (runs on every request):
    1. Catches unhandled exceptions → returns a generic 500 JSON; never a traceback.
    2. Adds security headers to every HTML response.
    """
    import json as _j
    try:
        response = await handler(request)
    except aiohttp_web.HTTPException:
        raise  # redirects and known HTTP errors pass through unchanged
    except Exception:
        log.exception("Unhandled web error %s %s", request.method, request.path)
        return aiohttp_web.Response(
            text=_j.dumps({"error": "Internal server error"}),
            status=500,
            content_type="application/json",
        )
    if response.content_type == "text/html":
        response.headers.update(_HTML_SECURITY_HEADERS)
    return response


async def _handle_404(request: aiohttp_web.Request):
    """
    Custom 404 — returns a safe JSON body instead of aiohttp's default page,
    which echoes the request path back and may leak internal routing detail.
    """
    import json as _j
    return aiohttp_web.Response(
        text=_j.dumps({"error": "Not found"}),
        status=404,
        content_type="application/json",
    )


async def handle_root(request):
    return aiohttp_web.Response(text=DASHBOARD_HTML, content_type="text/html")


async def handle_tos(request):
    return aiohttp_web.Response(text=TOS_HTML, content_type="text/html")


async def handle_privacy(request):
    return aiohttp_web.Response(text=PRIVACY_HTML, content_type="text/html")


async def handle_invite(request):
    app_id = bot.application_id or (bot.user.id if bot.user else None)
    if app_id:
        # permissions=8 (Administrator) is intentional — simplifies server setup.
        # The application_id is public data (visible in any server the bot joins).
        # Discord's OAuth flow still requires the user to own the target server.
        perms = 8
        url = f"https://discord.com/api/oauth2/authorize?client_id={app_id}&permissions={perms}&scope=bot%20applications.commands"
    else:
        url = "https://discord.com/developers/applications"
    raise aiohttp_web.HTTPFound(url)


async def handle_api_status(request):
    import json as _json
    online = bot.is_ready()
    latency = round(bot.latency * 1000) if online else None
    guild_count = len(bot.guilds) if online else 0

    # Uptime string
    delta = datetime.now(timezone.utc) - _start_time
    total_s = int(delta.total_seconds())
    h, rem = divmod(total_s, 3600)
    m, s = divmod(rem, 60)
    uptime = f"{h}h {m}m {s}s" if h else f"{m}m {s}s"

    # News channel name
    news_ch_name = None
    target_id = NEWS_CHANNEL_ID or NFLWATCH_CHANNEL_ID
    if target_id and online:
        ch = bot.get_channel(target_id)
        if ch:
            news_ch_name = f"#{ch.name}"

    payload = {
        "online": online,
        "latency_ms": latency,
        "guild_count": guild_count,
        "uptime": uptime,
        "news_channel": news_ch_name,
    }
    return aiohttp_web.Response(
        text=_json.dumps(payload),
        content_type="application/json",
        headers={"Access-Control-Allow-Origin": "*"},
    )


async def run_web_server():
    # Middleware order: rate limiter first (cheapest rejection), then security.
    app = aiohttp_web.Application(middlewares=[_rate_limit_middleware, _security_middleware])
    app.router.add_get("/",           handle_root)
    app.router.add_get("/tos",        handle_tos)
    app.router.add_get("/privacy",    handle_privacy)
    app.router.add_get("/invite",     handle_invite)
    app.router.add_get("/api/status", handle_api_status)
    # Catch-all: any unregistered path returns a safe 404 (never echoes the path)
    app.router.add_route("*", "/{path_info:.*}", _handle_404)
    runner = aiohttp_web.AppRunner(app)
    await runner.setup()
    site = aiohttp_web.TCPSite(runner, "0.0.0.0", 5000, reuse_address=True)
    await site.start()


async def main():
    global session
    session = aiohttp.ClientSession()
    await run_web_server()
    async with bot:
        await bot.start(TOKEN)


if __name__ == "__main__":
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
