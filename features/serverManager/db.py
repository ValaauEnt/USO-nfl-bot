"""Server manager database — auto-roles, welcome, and goodbye settings."""
import sqlite3
import json
from pathlib import Path

DB_PATH = Path("data/uso_bot.db")

_DEFAULT_WELCOME = "Welcome {user} to {server}! You are member #{memberCount}. 🎉"
_DEFAULT_GOODBYE = "Goodbye {user}, we hope to see you again! 👋"


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_server_manager_db():
    """Create the server_manager table if it doesn't exist."""
    with _get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS server_manager (
                guild_id         TEXT PRIMARY KEY,
                auto_roles       TEXT DEFAULT '[]',
                welcome_enabled  INTEGER DEFAULT 0,
                welcome_message  TEXT,
                goodbye_enabled  INTEGER DEFAULT 0,
                goodbye_message  TEXT
            );
        """)
        conn.commit()


def get_server_manager_config(guild_id: str) -> dict:
    """Return server manager config for a guild, with sensible defaults."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM server_manager WHERE guild_id = ?", (guild_id,)
        ).fetchone()
    if row is None:
        return {
            "guild_id":        guild_id,
            "auto_roles":      [],
            "welcome_enabled": False,
            "welcome_message": _DEFAULT_WELCOME,
            "goodbye_enabled": False,
            "goodbye_message": _DEFAULT_GOODBYE,
        }
    return {
        "guild_id":        guild_id,
        "auto_roles":      json.loads(row["auto_roles"] or "[]"),
        "welcome_enabled": bool(row["welcome_enabled"]),
        "welcome_message": row["welcome_message"] or _DEFAULT_WELCOME,
        "goodbye_enabled": bool(row["goodbye_enabled"]),
        "goodbye_message": row["goodbye_message"] or _DEFAULT_GOODBYE,
    }


def upsert_server_manager_config(guild_id: str, **kwargs):
    """Merge kwargs into the server manager config and persist."""
    config = get_server_manager_config(guild_id)
    for k, v in kwargs.items():
        if k in config:
            config[k] = v
    with _get_conn() as conn:
        conn.execute("""
            INSERT INTO server_manager
                (guild_id, auto_roles, welcome_enabled, welcome_message,
                 goodbye_enabled, goodbye_message)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                auto_roles       = excluded.auto_roles,
                welcome_enabled  = excluded.welcome_enabled,
                welcome_message  = excluded.welcome_message,
                goodbye_enabled  = excluded.goodbye_enabled,
                goodbye_message  = excluded.goodbye_message
        """, (
            guild_id,
            json.dumps(config["auto_roles"]),
            int(config["welcome_enabled"]),
            config["welcome_message"],
            int(config["goodbye_enabled"]),
            config["goodbye_message"],
        ))
        conn.commit()
