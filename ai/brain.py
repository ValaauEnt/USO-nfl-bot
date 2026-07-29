"""
Uce AI Brain — orchestrates OpenAI calls, tool dispatch, and memory.
"""
import os
import json
import logging
from typing import Callable, Awaitable

from openai import AsyncOpenAI

from ai.personalities import build_system_prompt, CORE_TRAITS
from ai.memory import (
    get_conversation_history,
    append_conversation,
    recall_user,
    recall_server,
    remember_user,
)
from ai.tools import TOOL_SCHEMAS

log = logging.getLogger("uso.brain")

_CHECKIN_SYSTEM = (
    "You are Uce, the funny and engaging NFL Discord bot. "
    + CORE_TRAITS
    + "\nKeep the message SHORT — one or two sentences max."
)

_MORNING_PROMPTS = [
    "Generate a unique, fun morning check-in for an NFL gaming Discord. "
    "Encourage conversation. Examples: 'Good morning everyone. What's everyone up to today?' / "
    "'Who's gaming today?' / 'Coffee or energy drinks?' — Be creative, NEVER repeat yourself.",
]

_NIGHT_PROMPTS = [
    "Generate a unique night check-in for an NFL gaming Discord. "
    "Reflective and casual. Examples: 'How'd today go?' / 'Biggest W today?' / "
    "'What made you laugh today?' — Be creative, NEVER repeat yourself.",
]


class AIBrain:
    """Central AI orchestrator. Pass a tools_executor coroutine at construction time."""

    def __init__(self, tools_executor: Callable[[str, dict], Awaitable[str]]):
        api_key = os.getenv("OPENAI_API_KEY")
        self.client: AsyncOpenAI | None = AsyncOpenAI(api_key=api_key) if api_key else None
        self.tools_executor = tools_executor

    @property
    def available(self) -> bool:
        return self.client is not None

    # ─── Main message processing ──────────────────────────────────────────────

    async def process_message(
        self,
        content: str,
        guild_id: str,
        user_id: str,
        user_name: str,
        channel_id: str,
        settings: dict,
    ) -> str:
        if not self.available:
            return (
                "My brain needs an OPENAI_API_KEY to work — ask an admin to add it. 🤖"
            )

        # Load memories
        user_mems   = recall_user(guild_id, user_id)   or {}
        server_mems = recall_server(guild_id)           or {}

        # Build system prompt with personality + memories
        system = build_system_prompt(settings, user_mems, server_mems)
        system += f"\n\nYou are talking to **{user_name}**."
        if user_mems.get("nickname"):
            system += f" Their nickname is **{user_mems['nickname']}**."

        # Assemble message list
        history  = get_conversation_history(channel_id)
        messages = [{"role": "system", "content": system}]
        messages.extend(history)
        messages.append({"role": "user", "content": content})

        # Log user message into history BEFORE the API call
        append_conversation(channel_id, "user", content)

        # ── First OpenAI call ─────────────────────────────────────────────────
        max_tok = 150 if settings.get("response_length", "short") == "short" else 600
        try:
            resp = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
                max_tokens=max_tok,
                temperature=0.85,
            )
        except Exception as exc:
            log.error("OpenAI first-pass error: %s", exc)
            return "Brain glitch — try again in a sec. 🧠💥"

        msg = resp.choices[0].message

        # ── Tool calls ────────────────────────────────────────────────────────
        if msg.tool_calls:
            tool_results = []
            for tc in msg.tool_calls:
                fn_name = tc.function.name
                try:
                    fn_args = json.loads(tc.function.arguments)
                except Exception:
                    fn_args = {}

                log.info("Tool call: %s(%s)", fn_name, fn_args)

                # Memory tool is handled locally
                if fn_name == "remember_user_fact":
                    remember_user(guild_id, user_id, fn_args.get("key", "note"), fn_args.get("value", ""))
                    result_text = f"Got it — remembered '{fn_args.get('key')}' for {user_name}."
                else:
                    try:
                        result_text = await self.tools_executor(fn_name, fn_args)
                    except Exception as exc:
                        log.error("Tool %s failed: %s", fn_name, exc)
                        result_text = f"Tool error: {exc}"

                tool_results.append({
                    "tool_call_id": tc.id,
                    "role": "tool",
                    "content": result_text,
                })

            # Reconstruct assistant turn with tool_calls field
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ],
            })
            messages.extend(tool_results)

            # ── Second pass with tool results ─────────────────────────────────
            try:
                resp2 = await self.client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    max_tokens=500,
                    temperature=0.85,
                )
                final_text = resp2.choices[0].message.content or ""
            except Exception as exc:
                log.error("OpenAI second-pass error: %s", exc)
                final_text = "Something went sideways processing the data. 😬"
        else:
            final_text = msg.content or ""

        if final_text:
            append_conversation(channel_id, "assistant", final_text)

        return final_text

    # ─── Check-in generation ──────────────────────────────────────────────────

    async def generate_checkin(
        self,
        checkin_type: str,
        server_memories: dict | None = None,
    ) -> str:
        """Generate a unique morning or night check-in message."""
        if not self.available:
            if checkin_type == "morning":
                return "Good morning! What's everyone up to today? 🏈"
            return "How'd today go? 🌙"

        base = _MORNING_PROMPTS[0] if checkin_type == "morning" else _NIGHT_PROMPTS[0]
        if server_memories:
            context = "\n".join(f"• {k}: {v}" for k, v in server_memories.items())
            base += f"\n\nServer context:\n{context}"

        try:
            resp = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": _CHECKIN_SYSTEM},
                    {"role": "user",   "content": base},
                ],
                max_tokens=80,
                temperature=1.1,
            )
            return resp.choices[0].message.content or ""
        except Exception as exc:
            log.error("Checkin generation error: %s", exc)
            if checkin_type == "morning":
                return "Good morning! Who's ready for some football? 🏈"
            return "That's a wrap on the day — how'd it go? 🌙"
