"""
Uce AI Brain — orchestrates OpenAI calls, tool dispatch, memory, and smart routing.

Routing priority (per spec):
  Level 1 — ESPN / sports APIs  (free, cached)     → espn_direct / espn_tool
  Level 2 — Web search          (future)            → falls through to LLM for now
  Level 3 — LLM only            (evergreen knowledge)
"""
import os
import json
import time
import logging
from datetime import datetime, timezone
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
from ai import router as _router
from ai import cache as _cache

log = logging.getLogger("uce.brain")

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

    # ─── Smart pre-fetch (Level 1 direct routes) ─────────────────────────────

    async def _prefetch(self, route: dict) -> tuple[str | None, bool, float]:
        """
        Fetch ESPN data for a direct route, with caching.
        Returns (data_text, cache_hit, api_ms).
        """
        cache_key = route["cache_key"]
        ttl_key   = route["ttl_key"]
        tool_name = route["tool_name"]
        fn_args   = route["fn_args"]

        # Cache check
        cached, hit = _cache.get(cache_key)
        if hit:
            return cached, True, 0.0

        # Fetch from API
        t0 = time.monotonic()
        try:
            data = await self.tools_executor(tool_name, fn_args)
        except Exception as exc:
            log.error("Pre-fetch %s failed: %s", tool_name, exc)
            return None, False, 0.0
        api_ms = (time.monotonic() - t0) * 1000

        _cache.set(cache_key, data, ttl_key)
        return data, False, api_ms

    # ─── Main message processing ─────────────────────────────────────────────

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
            return "My brain needs an OPENAI_API_KEY to work — ask an admin to add it. 🤖"

        # ── Current date (injected dynamically — never rely on model's internal clock) ──
        now      = datetime.now(timezone.utc)
        date_str = now.strftime("%A, %B %d, %Y")
        year_str = now.strftime("%Y")

        # ── Routing decision ──────────────────────────────────────────────────
        route        = _router.classify(content)
        intent       = route["intent"]
        source       = route["source"]
        prefetch_data: str | None = None
        cache_hit    = False
        api_ms       = 0.0
        web_search   = False   # not yet implemented; reserved for Level 2
        llm_used     = True    # always true when we reach OpenAI

        # ── Level 1 direct: pre-fetch ESPN data ──────────────────────────────
        if source == "espn_direct":
            prefetch_data, cache_hit, api_ms = await self._prefetch(route)

        # ── Memories ─────────────────────────────────────────────────────────
        user_mems   = recall_user(guild_id, user_id)   or {}
        server_mems = recall_server(guild_id)           or {}

        # ── System prompt ─────────────────────────────────────────────────────
        system = build_system_prompt(settings, user_mems, server_mems)

        # Date block — always first, so the model never guesses the year
        system = (
            f"Current date: {date_str}\n"
            f"Current year: {year_str}\n"
            f"Current NFL season year: {year_str}\n\n"
        ) + system

        system += f"\n\nYou are talking to **{user_name}**."
        if user_mems.get("nickname"):
            system += f" Their nickname is **{user_mems['nickname']}**."

        # Inject pre-fetched ESPN data so OpenAI formats it — no tool call needed
        if prefetch_data:
            system += (
                f"\n\n[LIVE {intent.upper()} DATA — already fetched, do NOT call any tools]\n"
                f"{prefetch_data}\n"
                "[Use this data to answer the user naturally. Summarize it conversationally.]"
            )

        # For espn_tool routes, hint OpenAI to use the right tool immediately
        if source == "espn_tool" and route["tool_name"]:
            system += (
                f"\n\n[ROUTING HINT] The user is asking about NFL {intent.replace('_', ' ')}. "
                f"Call the `{route['tool_name']}` tool to get accurate data before answering. "
                "Do not guess or make up stats, names, or scores."
            )

        # ── Message history ───────────────────────────────────────────────────
        history  = get_conversation_history(channel_id)
        messages = [{"role": "system", "content": system}]
        messages.extend(history)
        messages.append({"role": "user", "content": content})

        append_conversation(channel_id, "user", content)

        # ── Determine tool_choice ─────────────────────────────────────────────
        # espn_direct → data already injected, skip tool round-trip (saves 1 OpenAI call)
        # llm_only    → no tools needed (saves tool overhead)
        # everything else → auto (let OpenAI decide)
        if source in ("espn_direct", "llm_only", "off_topic"):
            tool_choice = "none"
            tools_arg   = None
        else:
            tool_choice = "auto"
            tools_arg   = TOOL_SCHEMAS

        # ── First OpenAI call ─────────────────────────────────────────────────
        _model   = "gpt-4o-mini"
        _endpoint = "chat.completions.create"
        max_tok  = 350 if settings.get("response_length", "short") == "short" else 600
        tools_enabled = tools_arg is not None
        tool_names = [t["function"]["name"] for t in (tools_arg or [])]

        call_kwargs: dict = dict(
            model       = _model,
            messages    = messages,
            tool_choice = tool_choice,
            max_tokens  = max_tok,
            temperature = 0.85,
        )
        if tools_arg:
            call_kwargs["tools"] = tools_arg

        # ── Full debug log (per spec) ─────────────────────────────────────────
        log.warning(
            "[AI REQUEST] model=%s | endpoint=%s | date_sent=%s | "
            "tools_enabled=%s | tool_choice=%s | tools=%s | "
            "intent=%s | source=%s | messages=%d",
            _model, _endpoint, date_str,
            tools_enabled, tool_choice, tool_names,
            intent, source, len(messages),
        )

        try:
            resp = await self.client.chat.completions.create(**call_kwargs)
        except Exception as exc:
            log.error("OpenAI first-pass error: %s", exc)
            return "Brain glitch — try again in a sec. 🧠💥"

        msg = resp.choices[0].message

        # ── Tool calls (for auto routes) ──────────────────────────────────────
        if msg.tool_calls:
            tool_results = []
            for tc in msg.tool_calls:
                fn_name = tc.function.name
                try:
                    fn_args = json.loads(tc.function.arguments)
                except Exception:
                    fn_args = {}

                log.info("Tool call: %s(%s)", fn_name, fn_args)

                # Memory tool handled locally
                if fn_name == "remember_user_fact":
                    remember_user(
                        guild_id, user_id,
                        fn_args.get("key", "note"),
                        fn_args.get("value", ""),
                    )
                    result_text = f"Got it — remembered '{fn_args.get('key')}' for {user_name}."
                else:
                    # Check cache for this tool+args combo
                    ttl_key   = _router._TOOL_TTL_MAP.get(fn_name)
                    ck        = f"{fn_name}:{json.dumps(fn_args, sort_keys=True)}"
                    cached_r, chit = _cache.get(ck)
                    if chit:
                        result_text = cached_r
                        log.info("Tool cache HIT  %s", ck)
                    else:
                        t0 = time.monotonic()
                        try:
                            result_text = await self.tools_executor(fn_name, fn_args)
                        except Exception as exc:
                            log.error("Tool %s failed: %s", fn_name, exc)
                            result_text = f"Tool error: {exc}"
                        tool_ms = (time.monotonic() - t0) * 1000
                        if ttl_key and result_text and not result_text.startswith("Tool error"):
                            _cache.set(ck, result_text, ttl_key)
                        log.info("Tool %s  %.0fms", fn_name, tool_ms)

                tool_results.append({
                    "tool_call_id": tc.id,
                    "role":         "tool",
                    "content":      result_text,
                })

            # Reconstruct assistant turn with tool_calls field
            messages.append({
                "role":       "assistant",
                "content":    msg.content or "",
                "tool_calls": [
                    {
                        "id":   tc.id,
                        "type": "function",
                        "function": {
                            "name":      tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ],
            })
            messages.extend(tool_results)

            # ── Second pass: format tool results ─────────────────────────────
            try:
                resp2 = await self.client.chat.completions.create(
                    model       = "gpt-4o-mini",
                    messages    = messages,
                    max_tokens  = 500,
                    temperature = 0.85,
                )
                final_text = resp2.choices[0].message.content or ""
            except Exception as exc:
                log.error("OpenAI second-pass error: %s", exc)
                final_text = "Something went sideways processing the data. 😬"
        else:
            final_text = msg.content or ""

        # ── Routing + response summary log ────────────────────────────────────
        used_web_search = any(
            (tc.function.name == "web_search" if hasattr(tc, "function") else False)
            for tc in (msg.tool_calls or [])
        ) if msg.tool_calls else False
        log.warning(
            "[AI RESPONSE] model=%s | date_sent=%s | intent=%s | source=%s | "
            "cache_hit=%s | espn_api_ms=%.0f | web_search_used=%s | llm_used=%s | "
            "reply_len=%d",
            _model, date_str, intent, source,
            cache_hit, api_ms, used_web_search, llm_used,
            len(final_text),
        )

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
                model       = "gpt-4o-mini",
                messages    = [
                    {"role": "system", "content": _CHECKIN_SYSTEM},
                    {"role": "user",   "content": base},
                ],
                max_tokens  = 80,
                temperature = 1.1,
            )
            return resp.choices[0].message.content or ""
        except Exception as exc:
            log.error("Checkin generation error: %s", exc)
            if checkin_type == "morning":
                return "Good morning! Who's ready for some football? 🏈"
            return "That's a wrap on the day — how'd it go? 🌙"
