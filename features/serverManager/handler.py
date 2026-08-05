"""Server manager event handlers — member join/leave."""
import logging
import discord
from features.serverManager.db import (
    get_server_manager_config,
    upsert_server_manager_config,
    _DEFAULT_WELCOME,
    _DEFAULT_GOODBYE,
)
from ai.settings import get_server_settings

log = logging.getLogger("uso.servermanager")

# ── Fallback messages when AI generation fails ────────────────────────────────
_FALLBACK_WELCOME = (
    "Welcome {mention} to **{server}**! "
    "You are member #{membercount}. Great to have you here! 🏈"
)
_FALLBACK_GOODBYE = (
    "Farewell, **{user}**! Thanks for being part of **{server}**. "
    "We hope to see you again! 👋"
)


def _apply_placeholders(template: str, member: discord.Member, guild: discord.Guild) -> str:
    """Replace all supported placeholders in a message template."""
    member_count = guild.member_count or "?"
    return (
        template
        .replace("{mention}",     member.mention)
        .replace("{user}",        member.display_name)
        .replace("{username}",    member.name)
        .replace("{server}",      guild.name)
        .replace("{membercount}", str(member_count))
        .replace("{memberCount}", str(member_count))   # legacy case
    )


async def _generate_ai_message(
    member: discord.Member,
    guild: discord.Guild,
    event_type: str,   # "welcome" or "goodbye"
    ai_brain,
) -> str | None:
    """
    Generate a dynamic welcome or goodbye message via OpenAI.
    Returns the generated text, or None if AI is unavailable or fails.
    """
    if ai_brain is None or not ai_brain.available:
        return None

    member_count = guild.member_count or "?"

    if event_type == "welcome":
        prompt = (
            f"Generate a warm, fun welcome message for {member.display_name} "
            f"(mention: {member.mention}) who just joined the Discord server '{guild.name}'. "
            f"They are member #{member_count}. "
            "Keep it under 2 sentences. Be friendly and engaging with an NFL/gaming vibe. "
            "Include their mention naturally."
        )
    else:
        prompt = (
            f"Generate a short, genuine goodbye message for {member.display_name} "
            f"who just left the Discord server '{guild.name}' (now {member_count} members). "
            "Keep it under 2 sentences. Be warm and casual with an NFL/gaming vibe."
        )

    try:
        response = await ai_brain.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are Uce, a funny and engaging NFL Discord bot with a Samoan-Pacific "
                        "Islander cultural vibe. Generate short, natural Discord messages — "
                        "no quotation marks, no hashtags, no bullet points."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=120,
            temperature=0.85,
        )
        text = response.choices[0].message.content.strip()
        return text if text else None
    except Exception as exc:
        log.warning("AI %s message generation failed: %s", event_type, exc)
        return None


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
                    f"Please use `/ai-channel` or `/{label.lower()}-channel` to set a new one."
                )
        except Exception:
            pass

    # Fallback: first configured AI channel
    for cid in fallback_ai_channels:
        ch = guild.get_channel(int(cid))
        if ch is not None:
            return ch

    return None


async def handle_member_join(member: discord.Member, ai_brain=None):
    """Auto-assign roles and send welcome message when a member joins."""
    guild    = member.guild
    guild_id = str(guild.id)
    config   = get_server_manager_config(guild_id)

    log.info(
        "MEMBER JOIN  guild=%s (%s)  member=%s (%s)  member_count=%s",
        guild.id, guild.name, member.id, member.display_name, guild.member_count,
    )

    # ── Auto-role assignment ─────────────────────────────────────────────────
    for role_id in config.get("auto_roles", []):
        try:
            role = guild.get_role(int(role_id))
            if role is None:
                log.warning("Auto-role %s not found in guild %s", role_id, guild_id)
                continue
            await member.add_roles(role, reason="Uce auto-role")
            log.info("Auto-role assigned: %s → %s", member.display_name, role.name)
        except discord.Forbidden:
            log.warning(
                "Missing Manage Roles permission (or role hierarchy) to assign "
                "role %s in guild %s", role_id, guild_id
            )
        except Exception as exc:
            log.error("Auto-role error guild=%s role=%s: %s", guild_id, role_id, exc)

    # ── Welcome message ──────────────────────────────────────────────────────
    if not config.get("welcome_enabled"):
        log.debug("Welcome messages disabled for guild %s — skipping", guild_id)
        return

    settings    = get_server_settings(guild_id)
    ai_channels = settings.get("ai_channels", [])

    channel = await _resolve_channel(
        guild, config, "welcome_channel_id", ai_channels, "Welcome"
    )
    if channel is None:
        log.warning(
            "Welcome message SKIPPED for guild %s — no welcome channel or AI channel configured. "
            "Use /set-welcome-channel or /ai-channel to configure one.", guild_id
        )
        return

    log.info("Welcome channel resolved: #%s (%s)", channel.name, channel.id)

    mode = config.get("welcome_mode", "ai")
    msg  = None

    if mode == "ai":
        log.info("Generating AI welcome message for %s in guild %s", member.display_name, guild_id)
        msg = await _generate_ai_message(member, guild, "welcome", ai_brain)
        if msg:
            log.info("AI welcome message generated successfully")
        else:
            log.warning("AI welcome generation failed — using fallback message")
            msg = _apply_placeholders(_FALLBACK_WELCOME, member, guild)
    else:
        # Custom mode
        template = config.get("welcome_message") or _DEFAULT_WELCOME
        msg      = _apply_placeholders(template, member, guild)
        log.info("Using custom welcome message for guild %s", guild_id)

    try:
        await channel.send(msg)
        log.info(
            "Welcome message sent  guild=%s  channel=#%s  mode=%s",
            guild_id, channel.name, mode,
        )
    except Exception as exc:
        log.error("Welcome message send error guild=%s: %s", guild_id, exc)


async def handle_member_remove(member: discord.Member, ai_brain=None):
    """Send goodbye message when a member leaves."""
    guild    = member.guild
    guild_id = str(guild.id)
    config   = get_server_manager_config(guild_id)

    log.info(
        "MEMBER LEAVE  guild=%s (%s)  member=%s (%s)",
        guild.id, guild.name, member.id, member.display_name,
    )

    if not config.get("goodbye_enabled"):
        log.debug("Goodbye messages disabled for guild %s — skipping", guild_id)
        return

    settings    = get_server_settings(guild_id)
    ai_channels = settings.get("ai_channels", [])

    channel = await _resolve_channel(
        guild, config, "goodbye_channel_id", ai_channels, "Goodbye"
    )
    if channel is None:
        log.warning(
            "Goodbye message SKIPPED for guild %s — no goodbye channel or AI channel configured. "
            "Use /set-goodbye-channel or /ai-channel to configure one.", guild_id
        )
        return

    log.info("Goodbye channel resolved: #%s (%s)", channel.name, channel.id)

    mode = config.get("goodbye_mode", "ai")
    msg  = None

    if mode == "ai":
        log.info("Generating AI goodbye message for %s in guild %s", member.display_name, guild_id)
        msg = await _generate_ai_message(member, guild, "goodbye", ai_brain)
        if msg:
            log.info("AI goodbye message generated successfully")
        else:
            log.warning("AI goodbye generation failed — using fallback message")
            msg = _apply_placeholders(_FALLBACK_GOODBYE, member, guild)
    else:
        # Custom mode
        template = config.get("goodbye_message") or _DEFAULT_GOODBYE
        msg      = _apply_placeholders(template, member, guild)
        log.info("Using custom goodbye message for guild %s", guild_id)

    try:
        await channel.send(msg)
        log.info(
            "Goodbye message sent  guild=%s  channel=#%s  mode=%s",
            guild_id, channel.name, mode,
        )
    except Exception as exc:
        log.error("Goodbye message send error guild=%s: %s", guild_id, exc)
