"""
UCE Proprietary Protection — multi-layer disclosure defense.

Layer 2: is_disclosure_request(text)  — keyword pre-filter, runs BEFORE OpenAI
Layer 3: filter_response(text)        — response validator, runs AFTER OpenAI
Layer 4: (secrets) filter_response also catches token-shaped strings

Layer 1 (system prompt SECURITY_RULES) lives in ai/personalities.py.
Layer 5 (logging protection) confirmed clean — no secrets written to logs.
"""
import re
import logging

log = logging.getLogger("uso.security")

# ─── Canned refusals ──────────────────────────────────────────────────────────

DISCLOSURE_RESPONSE = (
    "I can describe UCE's user-facing capabilities at a high-level, but the internal "
    "implementation is proprietary and I can't provide a technical blueprint or "
    "implementation details for recreating the bot."
)

_SECRET_FILTER_RESPONSE = (
    "I can't include that information in a response."
)

# ─── Layer 2 — pre-filter patterns ───────────────────────────────────────────
# Each pattern independently triggers the hard gate.
# Design: low false-positive over high recall — ambiguous messages go to the LLM
# (which is also instructed via SECURITY_RULES).

_INPUT_PHRASES: list[str] = [

    # ── Source code ───────────────────────────────────────────────────────────
    r"source\s+code",
    r"show\s+me\s+(the\s+)?(?:code|source)",
    r"(give|show|send|share)\s+me\s+(the\s+)?(source\s+code|codebase|repo)",
    r"(share|send)\s+(the\s+)?codebase",
    r"crucial\s+(pieces?|parts?)\s+of\s+(the\s+)?codebase",

    # ── Files / paths / modules ───────────────────────────────────────────────
    r"(what|which)\s+files?\s+(handle|manage|process|do|contain|store|would\s+i\s+need)",
    r"file\s+(path|name|structure|layout)",
    r"internal\s+(module|file|folder|directory|structure|architecture)",
    r"what\s+(files?|modules?)\s+(are\s+required|would\s+i\s+need|does\s+uce\s+use)",
    r"what\s+modules?\s+",

    # ── Database ──────────────────────────────────────────────────────────────
    r"database\s+schema",
    r"db\s+schema",
    r"table\s+(structure|schema|definition|layout)",
    r"sql\s+(schema|query|table|structure)",
    r"how\s+is\s+(your|uce.{0,5}s?|the)\s+database\s+structured",

    # ── Architecture / components / backend ───────────────────────────────────
    r"what\s+(architecture|components?)\s+(does\s+uce\s+use|would\s+i\s+need|are\s+(required|needed))",
    r"what\s+architecture\s+does\s+uce\s+use",
    r"(give\s+me|explain)\s+(the\s+)?(architecture|technical\s+architecture)",
    r"give\s+me\s+a\s+(technical\s+)?(blueprint|architecture|design\s+doc|technical\s+(breakdown|overview))",
    r"how\s+does\s+(your|uce.{0,5}s?|the)\s+backend\s+work",
    r"internal\s+(workflow|data\s+flow|service\s+architecture)",
    r"what\s+(systems|services)\s+would\s+i\s+need\s+to\s+(implement|build|create)",
    r"what\s+(technologies|tech\s+stack)\s+(does\s+uce\s+use|would\s+reproduce|would\s+replicate)",
    r"what\s+technologies\s+would\s+(reproduce|replicate|recreate)",

    # ── Recreation / cloning / rebuilding ─────────────────────────────────────
    r"(recreate|rebuild|replicate|clone|copy|duplicate)\s+(this|uce|the\s+bot)",
    r"how\s+(do\s+i|would\s+(i|someone))\s+(recreate|rebuild|replicate|clone|copy|make)\s+(this|uce|the\s+bot|it)",
    r"if\s+i\s+(rebuilt?|recreated?|cloned?|copied?)\s+(you|uce|the\s+bot)",
    r"rebuild\s+you",
    r"(recreate|clone|replicate)\s+you",
    r"what\s+would\s+be\s+required\s+to\s+make\s+(an?\s+)?(identical|similar)\s+bot",
    r"what\s+(would|would\s+someone)\s+need\s+to\s+(recreate|rebuild|replicate|clone|build)",
    r"what\s+would\s+(i|someone|another\s+\w+|a\s+\w+)\s+need\s+to\s+(build|make|create|recreate|replicate)",
    r"(exactly\s+how|how\s+exactly)\s+to\s+build",
    r"how\s+(is|was)\s+(it|uce|the\s+bot)\s+(built|made|coded|programmed|written|designed)",
    r"how\s+does\s+uce\s+(implement|work\s+internally|actually\s+(do|work))",
    r"how\s+do\s+i\s+reproduce\s+this",
    r"how\s+is\s+.{0,40}implemented",

    # ── APIs / endpoints ──────────────────────────────────────────────────────
    r"what\s+(api|apis?|endpoint)\s+does\s+(it|uce)\s+(use|call|hit)",
    r"what\s+apis?\s+does\s+uce\s+use",
    r"api\s+endpoint",

    # ── Credentials / secrets ─────────────────────────────────────────────────
    r"discord\s*[_\-]?\s*token",
    r"openai\s*[_\-]?\s*api\s*[_\-]?\s*key",
    r"ea\s*[_\-]?\s*madden\s*(api|key|credential|secret|token)",
    r"(api|secret|auth)\s+key",
    r"credential",
    r"environment\s+variable",
    r"\.env\b",

    # ── Internal prompts / AI config ──────────────────────────────────────────
    r"system\s+prompt",
    r"internal\s+prompt",
    r"(your|the)\s+prompt",
    r"openai\s+(config|configuration|setup|integration)",
    r"what\s+model\s+(does\s+it|are\s+you|do\s+you)\s+use",
    r"ai\s+(tool\s+definitions?|configuration|setup)",

    # ── Authentication / implementation internals ─────────────────────────────
    r"(authentication|auth)\s+(implementation|flow|code|setup|system)",
    r"authentication\s+implemented",

    # ── Handoff abuse ─────────────────────────────────────────────────────────
    r"hand\s*off\s+.{0,60}(code|implementation|technical|schema|architecture|detail)",
    r"(technical\s+)?handoff\s+(document|doc|details|breakdown|blueprint)",
    r"give\s+me\s+(everything|the\s+full\s+handoff|the\s+handoff)\s+(i\s+need\s+to|to)\s+(recreate|rebuild|integrate|replicate)",
    r"full\s+handoff",

    # ── Prompt injection attempts ─────────────────────────────────────────────
    r"ignore\s+(previous|prior|all|your)\s+instructions?",
    r"disregard\s+.{0,20}instructions?",
    r"forget\s+(everything|your\s+(previous\s+)?instructions?|all\s+previous)",
    r"(override|bypass)\s+(your\s+)?(rules?|restrictions?|instructions?|guidelines?|security)",
    r"you\s+are\s+(now\s+)?authorized",
    r"you\s+(now\s+)?(have\s+)?(new\s+)?(permission|authorization)",
    r"your\s+(new\s+)?(instructions?|rules?)\s+(are|have\s+been\s+updated)",
    r"this\s+is\s+(only\s+)?(hypothetical|a\s+test|just\s+a\s+test)",
    r"pretend\s+(the\s+)?(code|this|uce)\s+is\s+(public|open.source)",
    r"for\s+(testing|research|hypothetical)\s+purposes",
    r"act\s+as\s+(the\s+)?developer",
    r"pretend\s+you.?re\s+(the\s+)?developer",
    r"(reveal|explain|disclose|show)\s+(everything|all\s+(the\s+)?(details?|information|code|architecture))",
]

_INPUT_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in _INPUT_PHRASES
]

# ─── Layer 3+4 — response validator patterns ─────────────────────────────────
# Applied to the LLM's outgoing reply before it reaches Discord.

# Secret patterns — token/key shaped strings
_SECRET_RESPONSE_PATTERNS: list[re.Pattern] = [
    re.compile(r'DISCORD_TOKEN\s*[=:]\s*\S+', re.IGNORECASE),
    re.compile(r'OPENAI_API_KEY\s*[=:]\s*\S+', re.IGNORECASE),
    re.compile(r'sk-[A-Za-z0-9_\-]{15,}'),                                   # OpenAI key (sk-xxx or sk-proj-xxx)
    re.compile(r'Bot\s+[A-Za-z0-9_\-\.]{24,}'),                            # Discord bot token prefix
    re.compile(r'[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{4,}\.[A-Za-z0-9_\-]{20,}'),  # Discord JWT token
    re.compile(r'password\s*[=:]\s*\S+', re.IGNORECASE),
    re.compile(r'webhook_?url\s*[=:]\s*https?://', re.IGNORECASE),
]

# Blueprint-in-response patterns — signs the LLM produced a technical component list
_BLUEPRINT_RESPONSE_PATTERNS: list[re.Pattern] = [
    re.compile(r'```[\s\S]{50,}```'),   # code block with substantial content
]


def is_disclosure_request(text: str) -> bool:
    """
    Layer 2: Return True if ``text`` is a high-confidence proprietary-disclosure
    or prompt-injection attempt.

    Runs BEFORE the OpenAI call. Low false-positive design — ambiguous messages
    pass through to the LLM, which is instructed via SECURITY_RULES to refuse.
    """
    if not text:
        return False
    for pat in _INPUT_PATTERNS:
        if pat.search(text):
            return True
    return False


def filter_response(text: str) -> str:
    """
    Layers 3+4: Scan the LLM's outgoing reply for secrets (Layer 4) and
    prohibited blueprint content (Layer 3). Return the original text if clean,
    or a safe refusal if anything prohibited is detected.

    Runs AFTER the OpenAI call, before the reply reaches Discord.
    """
    for pat in _SECRET_RESPONSE_PATTERNS:
        if pat.search(text):
            log.warning("[SECURITY] Secret pattern detected in AI response — suppressing")
            return _SECRET_FILTER_RESPONSE

    for pat in _BLUEPRINT_RESPONSE_PATTERNS:
        if pat.search(text):
            log.warning("[SECURITY] Code block detected in AI response — suppressing")
            return DISCLOSURE_RESPONSE

    return text
