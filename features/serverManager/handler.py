"""Server manager event handlers — member join/leave."""
import logging
import discord
from features.serverManager.db import get_server_manager_config
from ai.settings import get_server_settings

log = logging.getLogger("uso.servermanager")


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
    if config.get("welcome_enabled"):
        settings    = get_server_settings(guild_id)
        ai_channels = settings.get("ai_channels", [])
        if not ai_channels:
            return  # No AI channel configured; skip silently
        channel = guild.get_channel(int(ai_channels[0]))
        if channel is None:
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
    if not ai_channels:
        return  # No AI channel configured; skip silently

    channel = guild.get_channel(int(ai_channels[0]))
    if channel is None:
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
