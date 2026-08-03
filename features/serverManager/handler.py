"""
Server Manager – event handlers.

Called from main.py on:
  • on_member_join  → assign_auto_roles + send_welcome
  • on_member_remove → send_goodbye
"""

import logging
import discord

from ai.settings import get_server_settings
from .db import get_sm_settings

log = logging.getLogger(__name__)


def _render(template: str, member: discord.Member) -> str:
    """Expand {user}, {server}, {memberCount} variables."""
    return (
        template
        .replace("{user}",        member.mention)
        .replace("{server}",      member.guild.name)
        .replace("{memberCount}", str(member.guild.member_count))
    )


async def assign_auto_roles(member: discord.Member) -> None:
    """Assign configured auto-roles to a new member."""
    guild    = member.guild
    settings = get_sm_settings(str(guild.id))
    role_ids = settings.get("auto_roles", [])

    if not role_ids:
        return

    me = guild.me
    if not me.guild_permissions.manage_roles:
        log.warning("[ServerManager] Missing Manage Roles permission in guild %s", guild.id)
        return

    for rid in role_ids:
        role = guild.get_role(int(rid))
        if role is None:
            log.warning("[ServerManager] Auto-role ID %s not found in guild %s", rid, guild.id)
            continue
        if role.position >= me.top_role.position:
            log.warning(
                "[ServerManager] Role %r is above my highest role in guild %s — skipping",
                role.name, guild.id,
            )
            continue
        try:
            await member.add_roles(role, reason="Uce auto-role")
            log.info("[ServerManager] Assigned role %r to %s in guild %s", role.name, member, guild.id)
        except discord.Forbidden:
            log.warning(
                "[ServerManager] Forbidden when assigning role %r to %s in guild %s",
                role.name, member, guild.id,
            )
        except Exception as exc:
            log.error("[ServerManager] Error assigning role: %s", exc)


async def send_welcome(member: discord.Member) -> None:
    """Send a welcome message to the configured AI channel."""
    guild    = member.guild
    sm       = get_sm_settings(str(guild.id))

    if not sm["welcome_enabled"]:
        return

    ss        = get_server_settings(str(guild.id))
    ai_chans  = [str(c) for c in ss.get("ai_channels", [])]

    if not ai_chans:
        log.info("[ServerManager] Welcome enabled but no AI channel configured for guild %s", guild.id)
        return

    channel = guild.get_channel(int(ai_chans[0]))
    if channel is None:
        return

    try:
        await channel.send(_render(sm["welcome_message"], member))
    except Exception as exc:
        log.error("[ServerManager] Error sending welcome: %s", exc)


async def send_goodbye(member: discord.Member) -> None:
    """Send a goodbye message to the configured AI channel."""
    guild = member.guild
    sm    = get_sm_settings(str(guild.id))

    if not sm["goodbye_enabled"]:
        return

    ss       = get_server_settings(str(guild.id))
    ai_chans = [str(c) for c in ss.get("ai_channels", [])]

    if not ai_chans:
        return

    channel = guild.get_channel(int(ai_chans[0]))
    if channel is None:
        return

    try:
        await channel.send(_render(sm["goodbye_message"], member))
    except Exception as exc:
        log.error("[ServerManager] Error sending goodbye: %s", exc)
