"""
Smart routing layer — classifies every question and maps it to the cheapest
reliable source before touching OpenAI.

Priority order (per spec):
  Level 1 — ESPN / sports APIs  (free, cached)
  Level 2 — Web search          (not yet wired; falls through to LLM)
  Level 3 — LLM only            (evergreen / conceptual knowledge)
"""
import re
import logging

log = logging.getLogger("uce.router")

# ── Direct routes ─────────────────────────────────────────────────────────────
# These need NO entity extraction from the message.
# Pre-fetch the data, inject it as context, skip OpenAI tool-calling round-trip.
#
# Format: intent_label → (tool_name, fn_args, ttl_key, keyword_patterns)

DIRECT_ROUTES: list[tuple[str, str, dict, str, list[str]]] = [
    (
        "scoreboard",
        "get_scoreboard",
        {},
        "scoreboard",
        [
            r"\b(scoreboard|live scores?|live game|games? (today|tonight|right now))\b",
            r"\bwho('s| is) winning\b",
            r"\bwho won (last night|today|yesterday)\b",
            r"\bwhat('s| is) the score\b",
            r"\b(nfl scores?|final scores?)\b",
        ],
    ),
    (
        "news",
        "get_headlines",
        {},
        "news",
        [
            r"\b(nfl news|nfl headlines?|nfl updates?|nfl today)\b",
            r"\blatest (nfl|football) (news|updates?|headlines?)\b",
            r"\bwhat('s| is) happening in (the )?nfl\b",
            r"\b(any|what) nfl news\b",
        ],
    ),
    (
        "trade_news",
        "get_trade_news",
        {},
        "trade_news",
        [
            r"\b(trade (news|rumors?|tracker)|nfl trades?|nfl transactions?)\b",
            r"\b(who got traded|any trades|recent trades|latest trades)\b",
            r"\b(free agent|waivers?|waiver wire|nfl rumors?)\b",
        ],
    ),
    (
        "leaders",
        "get_league_leaders",
        {},
        "leaders",
        [
            r"\b(league leaders?|stat leaders?|nfl leaders?|leading (the|in))\b",
            r"\b(top (passer|rusher|receiver|scorer|qb|rb|wr))\b",
            r"\b(most (passing |rushing |receiving )?(yards|tds|touchdowns|sacks|points))\b",
            r"\b(who (is|has) (the most|leading|tops?))\b",
        ],
    ),
]

# ── Tool-hint routes ───────────────────────────────────────────────────────────
# These require entity extraction (player name, team name).
# We don't pre-fetch; instead we hint OpenAI to use the right tool immediately.
#
# Format: intent_label → (tool_name, ttl_key, keyword_patterns)

TOOL_HINT_ROUTES: list[tuple[str, str, str, list[str]]] = [
    (
        "player_stats",
        "get_player_stats",
        "stats",
        [
            r"\b(stats?|statistics|how (many|much)|yards|touchdowns?|tds|sacks|catches|completions?|fantasy)\b",
            r"\b(last game|this season|season totals?|game log|performance)\b",
            r"\b(projected|injury report|is .+ injured|is .+ playing)\b",
        ],
    ),
    (
        "schedule",
        "get_team_schedule",
        "schedule",
        [
            r"\b(schedule|next game|when do(es)? (the )?[a-z]+ play|upcoming (game|matchup))\b",
            r"\b(who do the .+ play|matchup|bye week|home game|road game|away game)\b",
        ],
    ),
    (
        "player_info",
        "get_player_stats",
        "player",
        [
            r"\b(what team (does|is)|which team (does|is)|who does .+ play for)\b",
            r"\b(where (does|did) .+ play|.+ position|.+ jersey number|.+ age|.+ height|.+ weight)\b",
            r"\b(roster|who (is|are) on the)\b",
        ],
    ),
]

# ── LLM-only patterns ──────────────────────────────────────────────────────────
# Evergreen conceptual knowledge — no API needed, no tool calls, cheaper.

LLM_ONLY_PATTERNS: list[str] = [
    r"\b(explain|what is a|what are|what('s| is) a|how does|how do|teach me|difference between|definition of|meaning of)\b",
    r"\b(cover [0-9]|zone (coverage|defense)|man (coverage|defense)|blitz|formation|route|slant|post|corner route|out route|go route|fly route|screen pass|play action|option|spread|west coast|air raid|pro set|i-formation|shotgun)\b",
    r"\b(python|javascript|typescript|code|programming|algorithm|function|loop|variable|database|api|webhook|oauth|sdk)\b",
    r"\b(twitch|streaming|obs|discord (api|bot|webhook|oauth|developer))\b",
    r"\b(history of|all[- ]time|greatest of all time|goat|best ever|hall of fame|nfl history|super bowl history|founded in|was started)\b",
]

# ── Off-topic limiter ──────────────────────────────────────────────────────────
# Topics to handle briefly and not encourage — already in the system prompt,
# but flagged here so we can log it.

OFF_TOPIC_PATTERNS: list[str] = [
    r"\b(politics?|political|election|president|congress|senate|republican|democrat|liberal|conservative)\b",
    r"\b(religion|religious|god|jesus|allah|bible|quran|church|mosque|prayer)\b",
    r"\b(medical advice|diagnos|symptom|medication|drug|dose|treatment|disease)\b",
    r"\b(legal advice|lawsuit|attorney|lawyer|sue|court|trial|contract law)\b",
    r"\b(financial advice|invest|stock market|crypto|bitcoin|nft|portfolio|tax advice)\b",
]


# ── Tool name → TTL key (used by brain.py to cache auto tool-call results) ──
_TOOL_TTL_MAP: dict[str, str] = {
    "get_scoreboard":    "scoreboard",
    "get_headlines":     "news",
    "get_player_stats":  "stats",
    "get_team_schedule": "schedule",
    "get_trade_news":    "trade_news",
    "get_league_leaders":"leaders",
}


def classify(message: str) -> dict:
    """
    Classify the message and return a routing decision.

    Returns a dict:
      {
        "intent":     str,          # human-readable intent label
        "source":     str,          # "espn_direct" | "espn_tool" | "llm_only" | "general" | "off_topic"
        "tool_name":  str | None,   # tool to pre-fetch (direct) or hint (tool_hint)
        "fn_args":    dict,         # args for direct pre-fetch (empty for tool_hint)
        "ttl_key":    str | None,   # cache TTL category
        "cache_key":  str | None,   # cache store key
      }
    """
    text = message.lower().strip()

    # 1. LLM-only (evergreen knowledge — skip tools entirely)
    for pattern in LLM_ONLY_PATTERNS:
        if re.search(pattern, text):
            log.debug("Router → llm_only  pattern=%s", pattern[:40])
            return _result("llm_only", "llm_only", None, {}, None, None)

    # 2. Direct ESPN routes (no entity extraction)
    for intent, tool, fn_args, ttl_key, patterns in DIRECT_ROUTES:
        for pattern in patterns:
            if re.search(pattern, text):
                log.debug("Router → espn_direct  intent=%s", intent)
                return _result(intent, "espn_direct", tool, fn_args, ttl_key, tool)

    # 3. Tool-hint ESPN routes (entity extraction needed)
    for intent, tool, ttl_key, patterns in TOOL_HINT_ROUTES:
        for pattern in patterns:
            if re.search(pattern, text):
                log.debug("Router → espn_tool  intent=%s  tool=%s", intent, tool)
                return _result(intent, "espn_tool", tool, {}, ttl_key, None)

    # 4. Off-topic limiter (log it; LLM handles with personality constraints)
    for pattern in OFF_TOPIC_PATTERNS:
        if re.search(pattern, text):
            log.debug("Router → off_topic  pattern=%s", pattern[:40])
            return _result("off_topic", "off_topic", None, {}, None, None)

    # 5. General — let LLM decide with full tool access
    return _result("general", "general", None, {}, None, None)


def _result(intent, source, tool_name, fn_args, ttl_key, cache_key):
    return {
        "intent":    intent,
        "source":    source,
        "tool_name": tool_name,
        "fn_args":   fn_args,
        "ttl_key":   ttl_key,
        "cache_key": cache_key,
    }
