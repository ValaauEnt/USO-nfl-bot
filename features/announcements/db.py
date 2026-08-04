"""Announcements database — scheduled announcement storage and retrieval."""
import sqlite3
import time
from pathlib import Path

DB_PATH = Path("data/uso_bot.db")

TZ_MAP = {
    "ET":  "America/New_York",
    "CT":  "America/Chicago",
    "MT":  "America/Denver",
    "PT":  "America/Los_Angeles",
    "UTC": "UTC",
}


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_announcements_db():
    """Create the scheduled_announcements table if it doesn't exist."""
    with _get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS scheduled_announcements (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id     TEXT    NOT NULL,
                channel_id   TEXT    NOT NULL,
                message      TEXT    NOT NULL,
                frequency    TEXT    NOT NULL,
                time_str     TEXT    NOT NULL,
                day_of_week  TEXT,
                timezone     TEXT    NOT NULL DEFAULT 'America/New_York',
                enabled      INTEGER NOT NULL DEFAULT 1,
                created_by   TEXT,
                last_sent    INTEGER NOT NULL DEFAULT 0
            );
        """)
        conn.commit()


def add_scheduled_announcement(
    guild_id: str,
    channel_id: str,
    message: str,
    frequency: str,
    time_str: str,
    day_of_week: str | None,
    tz: str,
    created_by: str,
) -> int:
    """Insert a new scheduled announcement and return its id."""
    with _get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO scheduled_announcements
                (guild_id, channel_id, message, frequency, time_str,
                 day_of_week, timezone, enabled, created_by, last_sent)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, 0)
            """,
            (guild_id, channel_id, message, frequency, time_str,
             day_of_week, tz, created_by),
        )
        conn.commit()
        return cur.lastrowid


def get_scheduled_announcements(guild_id: str) -> list[dict]:
    """Return all enabled scheduled announcements for a guild."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM scheduled_announcements WHERE guild_id = ? AND enabled = 1",
            (guild_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_enabled_announcements() -> list[dict]:
    """Return every enabled announcement across all guilds (for the scheduler loop)."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM scheduled_announcements WHERE enabled = 1"
        ).fetchall()
    return [dict(r) for r in rows]


def remove_scheduled_announcement(guild_id: str, announcement_id: int) -> bool:
    """Soft-delete (disable) an announcement. Returns True if a row was affected."""
    with _get_conn() as conn:
        cur = conn.execute(
            "UPDATE scheduled_announcements SET enabled = 0 WHERE id = ? AND guild_id = ?",
            (announcement_id, guild_id),
        )
        conn.commit()
        return cur.rowcount > 0


def update_last_sent(announcement_id: int):
    """Stamp the current Unix timestamp as last_sent."""
    with _get_conn() as conn:
        conn.execute(
            "UPDATE scheduled_announcements SET last_sent = ? WHERE id = ?",
            (int(time.time()), announcement_id),
        )
        conn.commit()
