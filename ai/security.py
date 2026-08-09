"""
UCE Proprietary Protection — pre-LLM disclosure filter.

This module provides a keyword-based hard gate that runs BEFORE any OpenAI
call. If the user's message is a high-confidence recreation/disclosure
attempt, the bot returns a canned refusal without touching the LLM.

This is NOT a replacement for the SECURITY_RULES in the system prompt —
it is a defense-in-depth layer that catches the clearest cases regardless
of how the LLM is behaving.
"""
import re

# ── Canned refusal returned for blocked requests ──────────────────────────────
DISCLOSURE_RESPONSE = (
    "I can describe what that feature does at a high-level, but the internal "
    "implementation of UCE is proprietary and isn't available for disclosure "
    "without James's approval."
)

# ── Pattern groups — each list is OR'd together ───────────────────────────────

# Phrases that, on their own, strongly signal a disclosure attempt
_STRONG_PHRASES: list[str] = [
    r"show\s+me\s+(the\s+)?(?:code|source)",
    r"(give|show|send|share)\s+me\s+(the\s+)?(source\s+code|codebase|repo)",
    r"(share|send)\s+(the\s+)?codebase",
    r"credential",
    r"authentication\s+implemented",
    r"how\s+is\s+.{0,40}implemented",
    r"what\s+would\s+(i|someone)\s+need\s+to\s+(build|make|create|recreate|replicate)",
    r"source\s+code",
    r"(what|which)\s+files?\s+(handle|manage|process|do|contain|store)",
    r"file\s+(path|name|structure|layout)",
    r"internal\s+(module|file|folder|directory|structure|architecture)",
    r"database\s+schema",
    r"db\s+schema",
    r"table\s+(structure|schema|definition|layout)",
    r"sql\s+(schema|query|table|structure)",
    r"(recreate|rebuild|replicate|clone|copy|duplicate)\s+(this|uce|the\s+bot)",
    r"how\s+(do\s+i|would\s+(i|someone))\s+(recreate|rebuild|replicate|clone|copy|make)\s+(this|uce|the\s+bot|it)",
    r"how\s+does\s+uce\s+(implement|work\s+internally|actually\s+(do|work))",
    r"what\s+(api|endpoint)\s+does\s+(it|uce)\s+(use|call|hit)",
    r"api\s+endpoint",
    r"discord\s*[_\-]?\s*token",
    r"openai\s*[_\-]?\s*api\s*[_\-]?\s*key",
    r"ea\s*[_\-]?\s*madden\s*(api|key|credential|secret|token)",
    r"(api|secret|auth)\s+key",
    r"environment\s+variable",
    r"\.env\b",
    r"system\s+prompt",
    r"internal\s+prompt",
    r"(your|the)\s+prompt",
    r"what\s+(would|would\s+someone)\s+need\s+to\s+(recreate|rebuild|replicate|clone|build)",
    r"(exactly\s+how|how\s+exactly)\s+to\s+build",
    r"give\s+me\s+a\s+(blueprint|architecture|design\s+doc|technical\s+(breakdown|overview))",
    r"how\s+(is|was)\s+(it|uce|the\s+bot)\s+(built|made|coded|programmed|written|designed)",
    r"(authentication|auth)\s+(implementation|flow|code|setup|system)",
    r"openai\s+(config|configuration|setup|integration)",
    r"what\s+model\s+(does\s+it|are\s+you|do\s+you)\s+use",
    r"hand\s*off\s+.{0,60}(code|implementation|technical|schema|architecture|detail)",
    r"(technical\s+)?handoff\s+(document|doc|details|breakdown|blueprint)",
]

# Compile once at import time
_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in _STRONG_PHRASES
]


def is_disclosure_request(text: str) -> bool:
    """
    Return True if ``text`` is a high-confidence proprietary-disclosure attempt.

    Uses keyword/pattern matching only — no LLM call. Designed for low false
    positives: only blocks messages that clearly match a recreation or
    credential-extraction pattern. Ambiguous messages are left to the LLM,
    which is also instructed via SECURITY_RULES.
    """
    if not text:
        return False
    for pat in _PATTERNS:
        if pat.search(text):
            return True
    return False
