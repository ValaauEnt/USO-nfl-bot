"""
Server Manager – database helpers.

Stores per-guild configuration for:
  • auto_roles      – JSON list of role IDs to assign on member join
  • welcome_enabled – 0/1
  • welcome_message – template string (supports {user}, {server}, {memberCount})
  • goodbye_enabled – 0/1
  • goodbye_message – template string (supports {user}, {server}, {memberCount})

Channel configuration is NOT duplicated here.
The existing ai_channels field in server_settings is reused for welcome/goodbye delivery.
"""

import json
import time
from ai.settings import _get_conn

_DEFAULT_WELCOME = "Hey {user}, welcome to **{server}**! 🏈 You're member #{memberCount}."
_DEFAULT_GOODBYE = "**{user}** has left the server. We'll miss you. 👋"


def init_server_manager_db() -> None:
    """Create the server_manager table if it doesn't exist."""
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS server_manager (
                guild_id        TEXT PRIMARY KEY,
                auto_roles      TEXT    DEFAULT '[]',
                welcome_enabled INTEGER DEFAULT 0,
                welcome_message TEXT    DEFAULT '',
                goodbye_enabled INTEGER DEFAULT 0,
                goodbye_message TEXT    DEFAULT '',
                updated_at      REAL
            )
        """)
        conn.commit()


def get_sm_settings(guild_id: str) -> dict:
    """Return server_manager row as a plain dict, filling defaults for missing rows."""
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


def update_sm_settings(guild_id: str, **kwargs) -> dict:
    """
    Update one or more server_manager fields and return the full updated row.

    Accepted kwargs:
        auto_roles      (list[str])
        welcome_enabled (bool)
        welcome_message (str)
        goodbye_enabled (bool)
        goodbye_message (str)
    """
    current = get_sm_settings(guild_id)

    auto_roles      = kwargs.get("auto_roles",      current["auto_roles"])
    welcome_enabled = kwargs.get("welcome_enabled", current["welcome_enabled"])
    welcome_message = kwargs.get("welcome_message", current["welcome_message"])
    goodbye_enabled = kwargs.get("goodbye_enabled", current["goodbye_enabled"])
    goodbye_message = kwargs.get("goodbye_message", current["goodbye_message"])

    with _get_conn() as conn:
        conn.execute("""
            INSERT INTO server_manager
                (guild_id, auto_roles, welcome_enabled, welcome_message,
                 goodbye_enabled, goodbye_message, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                auto_roles      = excluded.auto_roles,
                welcome_enabled = excluded.welcome_enabled,
                welcome_message = excluded.welcome_message,
                goodbye_enabled = excluded.goodbye_enabled,
                goodbye_message = excluded.goodbye_message,
                updated_at      = excluded.updated_at
        """, (
            guild_id,
            json.dumps(auto_roles),
            int(welcome_enabled),
            welcome_message,
            int(goodbye_enabled),
            goodbye_message,
            time.time(),
        ))
        conn.commit()

    return get_sm_settings(guild_id)
