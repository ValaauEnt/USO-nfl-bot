"""Rate limiting — prevents AI spam."""
import time

USER_COOLDOWN    = 3.0   # seconds between responses per user
CHANNEL_COOLDOWN = 1.5   # seconds between responses per channel

_user_last:    dict[int, float] = {}
_channel_last: dict[int, float] = {}


def is_allowed(user_id: int, channel_id: int) -> bool:
    """Return True if both the user and channel are off cooldown."""
    now = time.time()
    user_ok    = now - _user_last.get(user_id, 0)    >= USER_COOLDOWN
    channel_ok = now - _channel_last.get(channel_id, 0) >= CHANNEL_COOLDOWN
    return user_ok and channel_ok


def stamp(user_id: int, channel_id: int) -> None:
    """Record that a response was just sent."""
    now = time.time()
    _user_last[user_id]       = now
    _channel_last[channel_id] = now
