"""Per-server settings stored in SQLite."""
import sqlite3
import json
from pathlib import Path

DB_PATH = Path("data/uso_bot.db")


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create all tables if they don't exist, and run column migrations."""
    with _get_conn() as conn:
        # ── Migrations for columns added after initial release ────────────────
        for col, definition in [
            ("response_length",      "TEXT DEFAULT 'short'"),
            ("headlines_channel_id", "TEXT DEFAULT NULL"),
            ("personality",          "TEXT DEFAULT 'locker_room'"),
            ("confidence",           "TEXT DEFAULT 'normal'"),
            ("sports_knowledge",     "TEXT DEFAULT 'football_expert'"),
        ]:
            try:
                conn.execute(
                    f"ALTER TABLE server_settings ADD COLUMN {col} {definition}"
                )
                conn.commit()
            except Exception:
                pass  # column already exists

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS server_settings (
                guild_id             TEXT PRIMARY KEY,
                humor_level          TEXT DEFAULT 'funny',
                roast_level          TEXT DEFAULT 'light',
                meme_level           TEXT DEFAULT 'medium',
                emoji_usage          TEXT DEFAULT 'balanced',
                profanity            TEXT DEFAULT 'none',
                interaction_mode     TEXT DEFAULT 'mention_only',
                response_length      TEXT DEFAULT 'short',
                ai_channels          TEXT DEFAULT '[]',
                morning_checkin      TEXT DEFAULT '{}',
                night_checkin        TEXT DEFAULT '{}',
                headlines_channel_id TEXT DEFAULT NULL,
                personality          TEXT DEFAULT 'locker_room',
                confidence           TEXT DEFAULT 'normal',
                sports_knowledge     TEXT DEFAULT 'football_expert'
            );
            CREATE TABLE IF NOT EXISTS user_memory (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id   TEXT NOT NULL,
                user_id    TEXT NOT NULL,
                key        TEXT NOT NULL,
                value      TEXT,
                updated_at REAL,
                UNIQUE(guild_id, user_id, key)
            );
            CREATE TABLE IF NOT EXISTS server_memory (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id   TEXT NOT NULL,
                key        TEXT NOT NULL,
                value      TEXT,
                updated_at REAL,
                UNIQUE(guild_id, key)
            );
            CREATE TABLE IF NOT EXISTS conversation_history (
                channel_id TEXT PRIMARY KEY,
                messages   TEXT DEFAULT '[]',
                updated_at REAL
            );
        """)
        conn.commit()


def get_server_settings(guild_id: str) -> dict:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM server_settings WHERE guild_id = ?", (guild_id,)
        ).fetchone()
    if row is None:
        return {
            "guild_id":            guild_id,
            "humor_level":         "funny",
            "roast_level":         "light",
            "meme_level":          "medium",
            "emoji_usage":         "balanced",
            "profanity":           "none",
            "interaction_mode":    "mention_only",
            "response_length":     "short",
            "ai_channels":         [],
            "morning_checkin":     {},
            "night_checkin":       {},
            "headlines_channel_id": None,
            "personality":         "locker_room",
            "confidence":          "normal",
            "sports_knowledge":    "football_expert",
        }
    return {
        "guild_id":            row["guild_id"],
        "humor_level":         row["humor_level"]      or "funny",
        "roast_level":         row["roast_level"]      or "light",
        "meme_level":          row["meme_level"]       or "medium",
        "emoji_usage":         row["emoji_usage"]      or "balanced",
        "profanity":           row["profanity"]        or "none",
        "interaction_mode":    row["interaction_mode"] or "mention_only",
        "response_length":     row["response_length"]  or "short",
        "ai_channels":         json.loads(row["ai_channels"]    or "[]"),
        "morning_checkin":     json.loads(row["morning_checkin"] or "{}"),
        "night_checkin":       json.loads(row["night_checkin"]   or "{}"),
        "headlines_channel_id": row["headlines_channel_id"],
        "personality":         row["personality"]       or "locker_room",
        "confidence":          row["confidence"]        or "normal",
        "sports_knowledge":    row["sports_knowledge"]  or "football_expert",
    }


def upsert_server_settings(guild_id: str, **kwargs):
    settings = get_server_settings(guild_id)
    for k, v in kwargs.items():
        settings[k] = v
    with _get_conn() as conn:
        conn.execute("""
            INSERT INTO server_settings
                (guild_id, humor_level, roast_level, meme_level, emoji_usage,
                 profanity, interaction_mode, response_length,
                 ai_channels, morning_checkin, night_checkin,
                 headlines_channel_id, personality, confidence, sports_knowledge)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                humor_level          = excluded.humor_level,
                roast_level          = excluded.roast_level,
                meme_level           = excluded.meme_level,
                emoji_usage          = excluded.emoji_usage,
                profanity            = excluded.profanity,
                interaction_mode     = excluded.interaction_mode,
                response_length      = excluded.response_length,
                ai_channels          = excluded.ai_channels,
                morning_checkin      = excluded.morning_checkin,
                night_checkin        = excluded.night_checkin,
                headlines_channel_id = excluded.headlines_channel_id,
                personality          = excluded.personality,
                confidence           = excluded.confidence,
                sports_knowledge     = excluded.sports_knowledge
        """, (
            guild_id,
            settings["humor_level"],
            settings["roast_level"],
            settings["meme_level"],
            settings["emoji_usage"],
            settings["profanity"],
            settings["interaction_mode"],
            settings["response_length"],
            json.dumps(settings["ai_channels"]),
            json.dumps(settings["morning_checkin"]),
            json.dumps(settings["night_checkin"]),
            settings["headlines_channel_id"],
            settings["personality"],
            settings["confidence"],
            settings["sports_knowledge"],
        ))
        conn.commit()
