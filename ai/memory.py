"""SQLite-backed memory for users and servers."""
import json
import time
from ai.settings import _get_conn

MAX_HISTORY          = 20   # messages kept per channel
HISTORY_MAX_AGE_SECS = 4 * 3600  # conversations older than 4 h are stale — start fresh

# Pre-context: ambient channel messages recorded before UCE is addressed.
# Short window — we only need to know what the channel was just discussing.
MAX_PRE_CONTEXT          = 10   # ambient messages buffered per channel
PRE_CONTEXT_MAX_AGE_SECS = 1800  # 30 min — ambient context goes stale quickly


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
            "SELECT messages, updated_at FROM conversation_history WHERE channel_id=?",
            (channel_id,),
        ).fetchone()
    if not row:
        return []
    # Drop history that's older than HISTORY_MAX_AGE_SECS — stale context
    # causes the model to repeat outdated facts (wrong year, old scores, etc.)
    age = time.time() - (row["updated_at"] or 0)
    if age > HISTORY_MAX_AGE_SECS:
        return []
    return json.loads(row["messages"] or "[]")


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


# ── Channel pre-context (ambient messages before UCE is addressed) ────────────
# Records every non-bot message in AI-enabled channels so that when UCE IS
# triggered, it can see what the channel was discussing moments before —
# including conversations that never directly involved UCE.
# This is kept separate from conversation_history (which only tracks UCE turns)
# and is intentionally short-lived (30-minute TTL).

def append_channel_context(channel_id: str, author_name: str, content: str):
    """Record an ambient channel message for pre-context use.

    Only stores messages up to 500 chars — long pastes / walls of text are
    truncated to avoid inflating the context unnecessarily.
    """
    content = content[:500] if content else ""
    if not content.strip():
        return
    messages = _load_channel_context_raw(channel_id)
    messages.append({"author": author_name, "content": content})
    if len(messages) > MAX_PRE_CONTEXT:
        messages = messages[-MAX_PRE_CONTEXT:]
    with _get_conn() as conn:
        conn.execute("""
            INSERT INTO channel_context (channel_id, messages, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(channel_id) DO UPDATE SET
                messages   = excluded.messages,
                updated_at = excluded.updated_at
        """, (channel_id, json.dumps(messages), time.time()))
        conn.commit()


def get_channel_context(channel_id: str) -> list[dict]:
    """Return recent ambient channel messages, or [] if absent / expired."""
    return _load_channel_context_raw(channel_id)


def _load_channel_context_raw(channel_id: str) -> list[dict]:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT messages, updated_at FROM channel_context WHERE channel_id=?",
            (channel_id,),
        ).fetchone()
    if not row:
        return []
    age = time.time() - (row["updated_at"] or 0)
    if age > PRE_CONTEXT_MAX_AGE_SECS:
        return []
    return json.loads(row["messages"] or "[]")
