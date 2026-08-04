"""Server manager event handlers — member join/leave."""
import logging
import discord
from features.serverManager.db import get_server_manager_config, upsert_server_manager_config
from ai.settings import get_server_settings

log = logging.getLogger("uso.servermanager")


async def _resolve_channel(
    guild: discord.Guild,
    config: dict,
    channel_key: str,
    fallback_ai_channels: list,
    label: str,
) -> discord.TextChannel | None:
    """
    Resolve a text channel for welcome or goodbye messages.

    Priority:
      1. Dedicated channel stored in config[channel_key]
      2. First AI channel (fallback)

    If the dedicated channel ID is stored but the channel no longer exists,
    DM the guild owner, clear the setting, and fall back to the AI channel.
    """
    dedicated_id = config.get(channel_key)
    if dedicated_id:
        ch = guild.get_channel(int(dedicated_id))
        if ch is not None:
            return ch
        # Channel was deleted — notify owner and clear the setting
        log.warning(
            "%s channel %s no longer exists in guild %s — clearing setting",
            label, dedicated_id, guild.id,
        )
        try:
            upsert_server_manager_config(str(guild.id), **{channel_key: None})
        except Exception as exc:
            log.error("Failed to clear stale %s channel: %s", channel_key, exc)
        try:
            owner = guild.owner
            if owner:
                await owner.send(
                    f"⚠️ **{guild.name}**: The {label} channel I was posting to "
                    f"(`#{dedicated_id}`) no longer exists. "
                    f"Please use `/ai-channel` to set a new {label.lower()} channel."
                )
        except Exception:
            pass
        # Fall through to AI-channel fallback below

    # Fallback: first configured AI channel
    for cid in fallback_ai_channels:
        ch = guild.get_channel(int(cid))
        if ch is not None:
            return ch

    return None


async def handle_member_join(member: discord.Member):
    """Auto-assign roles and send welcome message when a member joins."""
    guild    = member.guild
    guild_id = str(guild.id)
    config   = get_server_manager_config(guild_id)

    # ── Auto-role assignment ─────────────────────────────────────────────────
    for role_id in config.get("auto_roles", []):
        try:
            role = guild.get_role(int(role_id))
            if role is None:
                log.warning("Auto-role %s not found in guild %s", role_id, guild_id)
                continue
            await member.add_roles(role, reason="Uce auto-role")
        except discord.Forbidden:
            log.warning(
                "Missing Manage Roles permission (or role hierarchy) to assign "
                "role %s in guild %s", role_id, guild_id
            )
        except Exception as exc:
            log.error("Auto-role error guild=%s role=%s: %s", guild_id, role_id, exc)

    # ── Welcome message ──────────────────────────────────────────────────────
    if not config.get("welcome_enabled"):
        return

    settings    = get_server_settings(guild_id)
    ai_channels = settings.get("ai_channels", [])

    channel = await _resolve_channel(
        guild, config, "welcome_channel_id", ai_channels, "Welcome"
    )
    if channel is None:
        log.warning(
            "Welcome message skipped — no channel configured for guild %s. "
            "Use /ai-channel to set a welcome channel.", guild_id
        )
        return

    member_count = guild.member_count or "?"
    msg = (
        config["welcome_message"]
        .replace("{user}", member.mention)
        .replace("{server}", guild.name)
        .replace("{memberCount}", str(member_count))
    )
    try:
        await channel.send(msg)
    except Exception as exc:
        log.error("Welcome message error guild=%s: %s", guild_id, exc)


async def handle_member_remove(member: discord.Member):
    """Send goodbye message when a member leaves."""
    guild    = member.guild
    guild_id = str(guild.id)
    config   = get_server_manager_config(guild_id)

    if not config.get("goodbye_enabled"):
        return

    settings    = get_server_settings(guild_id)
    ai_channels = settings.get("ai_channels", [])

    channel = await _resolve_channel(
        guild, config, "goodbye_channel_id", ai_channels, "Goodbye"
    )
    if channel is None:
        log.warning(
            "Goodbye message skipped — no channel configured for guild %s. "
            "Use /ai-channel to set a goodbye channel.", guild_id
        )
        return

    member_count = guild.member_count or "?"
    msg = (
        config["goodbye_message"]
        .replace("{user}", member.display_name)
        .replace("{server}", guild.name)
        .replace("{memberCount}", str(member_count))
    )
    try:
        await channel.send(msg)
    except Exception as exc:
        log.error("Goodbye message error guild=%s: %s", guild_id, exc)
