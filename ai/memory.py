"""SQLite-backed memory for users and servers."""
import json
import time
from ai.settings import _get_conn

MAX_HISTORY = 20  # messages kept per channel


# ── User memory ──────────────────────────────────────────────────────────────

def remember_user(guild_id: str, user_id: str, key: str, value):
    with _get_conn() as conn:
        conn.execute("""
            INSERT INTO user_memory (guild_id, user_id, key, value, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id, key) DO UPDATE SET
                value      = excluded.value,
                updated_at = excluded.updated_at
        """, (guild_id, user_id, key, json.dumps(value), time.time()))
        conn.commit()


def recall_user(guild_id: str, user_id: str, key: str | None = None):
    with _get_conn() as conn:
        if key:
            row = conn.execute(
                "SELECT value FROM user_memory WHERE guild_id=? AND user_id=? AND key=?",
                (guild_id, user_id, key),
            ).fetchone()
            return json.loads(row["value"]) if row else None
        rows = conn.execute(
            "SELECT key, value FROM user_memory WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        ).fetchall()
        return {r["key"]: json.loads(r["value"]) for r in rows}


def forget_user(guild_id: str, user_id: str, key: str | None = None):
    with _get_conn() as conn:
        if key:
            conn.execute(
                "DELETE FROM user_memory WHERE guild_id=? AND user_id=? AND key=?",
                (guild_id, user_id, key),
            )
        else:
            conn.execute(
                "DELETE FROM user_memory WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            )
        conn.commit()


# ── Server memory ─────────────────────────────────────────────────────────────

def remember_server(guild_id: str, key: str, value):
    with _get_conn() as conn:
        conn.execute("""
            INSERT INTO server_memory (guild_id, key, value, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, key) DO UPDATE SET
                value      = excluded.value,
                updated_at = excluded.updated_at
        """, (guild_id, key, json.dumps(value), time.time()))
        conn.commit()


def recall_server(guild_id: str, key: str | None = None):
    with _get_conn() as conn:
        if key:
            row = conn.execute(
                "SELECT value FROM server_memory WHERE guild_id=? AND key=?",
                (guild_id, key),
            ).fetchone()
            return json.loads(row["value"]) if row else None
        rows = conn.execute(
            "SELECT key, value FROM server_memory WHERE guild_id=?",
            (guild_id,),
        ).fetchall()
        return {r["key"]: json.loads(r["value"]) for r in rows}


# ── Conversation history ───────────────────────────────────────────────────────

def get_conversation_history(channel_id: str) -> list[dict]:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT messages FROM conversation_history WHERE channel_id=?",
            (channel_id,),
        ).fetchone()
    return json.loads(row["messages"] or "[]") if row else []


def append_conversation(channel_id: str, role: str, content: str):
    history = get_conversation_history(channel_id)
    history.append({"role": role, "content": content})
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]
    with _get_conn() as conn:
        conn.execute("""
            INSERT INTO conversation_history (channel_id, messages, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(channel_id) DO UPDATE SET
                messages   = excluded.messages,
                updated_at = excluded.updated_at
        """, (channel_id, json.dumps(history), time.time()))
        conn.commit()


def clear_conversation(channel_id: str):
    with _get_conn() as conn:
        conn.execute(
            "DELETE FROM conversation_history WHERE channel_id=?", (channel_id,)
        )
        conn.commit()
