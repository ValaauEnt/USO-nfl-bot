---
name: UCE AI tool auth pattern
description: How AI action tools verify permissions and track usage limits
---

Every AI Discord action tool inside `_ai_tools_executor` must:
1. Read `guild = _ctx_guild.get()` and `author = _ctx_author.get()` from ContextVars
2. Check `perms = author.guild_permissions` and verify `perms.administrator or perms.manage_guild`
3. Check and increment `_ctx_action_count` against `_MAX_AI_ACTIONS = 5`
4. Log with `log.info("[AI ACTION] ...")` before performing the Discord action

Failure response for auth: exact string "🏈 Flag on the play! You don't have the permissions for this one. You need Administrator or Manage Server to make this call. 🚩"

`_ctx_action_count` is reset to 0 in `on_message` at the same site as `_ctx_guild.set()` / `_ctx_author.set()`.

**Why:** The AI runs in a different auth context from slash commands. It has no `interaction.user` — the ContextVars carry the original message author so the tool executor can verify independently.

**How to apply:** Destructive tools (delete channel, rename server) are deliberately NOT exposed — they remain blocked until explicitly approved by the user. The `announce` tool caps at 3 channels per call.
