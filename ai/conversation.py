"""
Conversation mode tracking.

After USO is @mentioned, it stays active in that channel for CONVERSATION_TTL seconds.
During this window users don't need to @mention — USO follows the conversation naturally.
"""
import time

CONVERSATION_TTL = 300  # 5 minutes

_active: dict[int, float] = {}  # channel_id -> last_activity_timestamp


def activate(channel_id: int) -> None:
    """Start or reset the active window for a channel."""
    _active[channel_id] = time.time()


def is_active(channel_id: int) -> bool:
    """Return True if the channel is within the active conversation window."""
    last = _active.get(channel_id)
    if last is None:
        return False
    if time.time() - last > CONVERSATION_TTL:
        _active.pop(channel_id, None)
        return False
    return True


def deactivate(channel_id: int) -> None:
    """Manually end an active conversation."""
    _active.pop(channel_id, None)


def cleanup() -> None:
    """Purge expired sessions — call periodically."""
    now = time.time()
    expired = [cid for cid, t in list(_active.items()) if now - t > CONVERSATION_TTL]
    for cid in expired:
        _active.pop(cid, None)
