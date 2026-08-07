"""
Check-in scheduler — posts morning/night messages per server settings.
Called every minute from a discord.ext.tasks loop in main.py.
"""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

log = logging.getLogger("uso.scheduler")

# Tracks (guild_id, checkin_type, HHMM) so we only post once per minute slot
_posted: set[tuple[str, str, str]] = set()


async def run_checkins(bot, brain, get_settings_fn, recall_server_fn) -> None:
    """Iterate all guilds and post check-ins whose time has arrived."""
    now_utc = datetime.now(ZoneInfo("UTC"))

    for guild in bot.guilds:
        gid = str(guild.id)
        settings = get_settings_fn(gid)
        server_mems = recall_server_fn(gid) or {}

        for checkin_type in ("morning_checkin", "night_checkin"):
            cfg = settings.get(checkin_type, {})
            if not cfg.get("enabled"):
                continue

            channel_id = cfg.get("channel_id")
            time_str   = cfg.get("time", "08:00")
            tz_name    = cfg.get("timezone", "America/New_York")

            if not channel_id:
                continue

            try:
                tz = ZoneInfo(tz_name)
            except ZoneInfoNotFoundError:
                tz = ZoneInfo("America/New_York")

            now_local = datetime.now(tz)
            try:
                h, m = map(int, time_str.split(":"))
            except ValueError:
                continue

            # Match current HH:MM
            if now_local.hour != h or now_local.minute != m:
                continue

            # Deduplicate — only post once per minute slot per guild
            slot_key = (gid, checkin_type, f"{now_local.strftime('%Y%m%d%H%M')}")
            if slot_key in _posted:
                continue
            _posted.add(slot_key)

            # Keep _posted from growing unbounded
            if len(_posted) > 10_000:
                _posted.clear()

            channel = bot.get_channel(int(channel_id))
            if channel is None:
                continue

            mood = "morning" if checkin_type == "morning_checkin" else "night"
            try:
                message = await brain.generate_checkin(mood, server_mems, settings)
                if message:
                    await channel.send(message)
            except Exception as exc:
                log.error("Check-in post failed for guild %s: %s", gid, exc)
