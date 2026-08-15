"""
Tests for UCE permission fixes and new AI action tools.

Verifies:
  - All six previously-unprotected commands now have user auth checks
  - New AI tool schemas exist (create_channel, create_category, announce)
  - /ask slash command is removed from the module
  - _ctx_action_count ContextVar is declared
  - extract_stats_from_gamelog tags entries with season_label
  - build_live_game_embed is importable and builds a valid embed
"""

import sys
import inspect
import pathlib
import pytest
import discord

# ---------------------------------------------------------------------------
# Helpers — import main and also load its raw source for text-based checks.
# discord.py wraps slash-command handlers in Command objects so inspect.getsource
# on getattr(m, "some_cmd") receives a Command, not a function.  We search the
# raw source file directly for reliable pattern matching.
# ---------------------------------------------------------------------------

import main as m

_MAIN_SRC: str = pathlib.Path("main.py").read_text(encoding="utf-8")


def _cmd_source(cmd_name: str) -> str:
    """Return the source block for a slash command by name, searching main.py.

    Extracts from 'async def <cmd_name>' to just before the next 'async def '
    or top-level decorator at the same indentation level.
    """
    lines = _MAIN_SRC.splitlines()
    start = None
    for i, line in enumerate(lines):
        if f"async def {cmd_name}(" in line:
            start = i
            break
    assert start is not None, f"async def {cmd_name}() not found in main.py"
    # Collect lines until the next top-level async def / @bot / @tasks
    block = []
    for line in lines[start:]:
        if block and (
            line.startswith("async def ")
            or line.startswith("@bot.")
            or line.startswith("@tasks.")
            or line.startswith("class ")
        ):
            break
        block.append(line)
    return "\n".join(block)


# ---------------------------------------------------------------------------
# 1. The six previously-unprotected commands now have permission guards
# ---------------------------------------------------------------------------

PROTECTED_CMDS = [
    "create_channel",
    "delete_channel",
    "rename_server",
    "create_category",
    "morning_checkin",
    "night_checkin",
]

PERM_SENTINEL = "administrator or perms.manage_guild"


@pytest.mark.parametrize("cmd_name", PROTECTED_CMDS)
def test_command_has_perm_check(cmd_name):
    """Each admin-only command must check administrator|manage_guild in its source."""
    src = _cmd_source(cmd_name)
    assert PERM_SENTINEL in src, (
        f"'{cmd_name}' is missing the 'administrator or perms.manage_guild' permission check"
    )


@pytest.mark.parametrize("cmd_name", PROTECTED_CMDS)
def test_command_sends_flag_message_on_denied(cmd_name):
    """The exact denial message must be present in each command's source."""
    src = _cmd_source(cmd_name)
    assert "Flag on the play" in src, (
        f"'{cmd_name}' is missing the UCE-standard 'Flag on the play' denial message"
    )


# ---------------------------------------------------------------------------
# 2. /ask command is removed
# ---------------------------------------------------------------------------

def test_ask_command_not_in_tree():
    """/ask must not be registered as a bot.tree command."""
    assert 'name="ask"' not in _MAIN_SRC, "/ask slash command is still registered"


def test_ask_function_not_defined():
    """The 'ask' slash-command async def should be absent from main.py."""
    # We check the raw source so that decorator wrappers don't obscure it
    assert "async def ask(" not in _MAIN_SRC, (
        "The 'ask' function is still defined in main — it should have been removed"
    )


# ---------------------------------------------------------------------------
# 3. New AI tool schemas are present
# ---------------------------------------------------------------------------

from ai.tools import TOOL_SCHEMAS

NEW_TOOLS = ["create_channel", "create_category", "announce"]


@pytest.mark.parametrize("tool_name", NEW_TOOLS)
def test_new_tool_schema_exists(tool_name):
    """Each new server-management tool must have a schema in TOOL_SCHEMAS."""
    names = {t["function"]["name"] for t in TOOL_SCHEMAS}
    assert tool_name in names, f"Tool '{tool_name}' missing from TOOL_SCHEMAS"


def test_tool_count_increased():
    """TOOL_SCHEMAS should now have at least 18 tools (15 original + 3 new)."""
    assert len(TOOL_SCHEMAS) >= 18, (
        f"Expected ≥18 tool schemas, got {len(TOOL_SCHEMAS)}"
    )


def test_get_headlines_no_source_names():
    """get_headlines description must not reveal specific provider names."""
    headlines_schema = next(
        (t for t in TOOL_SCHEMAS if t["function"]["name"] == "get_headlines"), None
    )
    assert headlines_schema is not None
    desc = headlines_schema["function"]["description"].lower()
    for provider in ("espn", "yahoo", "pro football talk", "profootballtalk"):
        assert provider not in desc, (
            f"Tool description reveals source name '{provider}' — must be generic"
        )


# ---------------------------------------------------------------------------
# 4. _ctx_action_count ContextVar and _MAX_AI_ACTIONS are declared
# ---------------------------------------------------------------------------

def test_ctx_action_count_exists():
    """_ctx_action_count ContextVar must be declared in main."""
    assert hasattr(m, "_ctx_action_count"), "_ctx_action_count not found in main"


def test_max_ai_actions_exists():
    """_MAX_AI_ACTIONS constant must be declared in main."""
    assert hasattr(m, "_MAX_AI_ACTIONS"), "_MAX_AI_ACTIONS not found in main"
    assert isinstance(m._MAX_AI_ACTIONS, int), "_MAX_AI_ACTIONS must be an int"
    assert 1 <= m._MAX_AI_ACTIONS <= 20, "_MAX_AI_ACTIONS should be a reasonable limit (1–20)"


# ---------------------------------------------------------------------------
# 5. extract_stats_from_gamelog tags each entry with season_label
# ---------------------------------------------------------------------------

def test_gamelog_entries_have_season_label():
    """extract_stats_from_gamelog must add season_label to every entry."""
    sample_gamelog = {
        "seasonTypes": [
            {
                "displayName": "Regular Season",
                "categories": [
                    {
                        "events": [
                            {
                                "atVs": "@ BUF",
                                "opponent": {"displayName": "Buffalo Bills"},
                                "stats": [
                                    {"displayName": "Passing Yards", "displayValue": "312"},
                                    {"displayName": "TDs", "displayValue": "2"},
                                ],
                            }
                        ]
                    }
                ],
            },
            {
                "displayName": "Post Season",
                "categories": [
                    {
                        "events": [
                            {
                                "atVs": "vs KC",
                                "opponent": {"displayName": "Kansas City Chiefs"},
                                "stats": [
                                    {"displayName": "Passing Yards", "displayValue": "280"},
                                ],
                            }
                        ]
                    }
                ],
            },
        ]
    }
    entries = m.extract_stats_from_gamelog(sample_gamelog)
    assert len(entries) >= 2, "Expected at least 2 entries"
    for entry in entries:
        assert "season_label" in entry, f"Entry missing 'season_label': {entry}"

    labels = {e["season_label"] for e in entries}
    assert "Regular Season" in labels
    assert "Post Season" in labels


def test_gamelog_entries_deduplicated():
    """Events appearing in multiple categories should only generate one entry."""
    shared_event = {
        "eventId": "abc123",
        "atVs": "@ DAL",
        "opponent": {"displayName": "Dallas Cowboys"},
        "stats": [{"displayName": "Rush Yards", "displayValue": "88"}],
    }
    sample_gamelog = {
        "seasonTypes": [
            {
                "displayName": "Regular Season",
                "categories": [
                    {"events": [shared_event]},
                    {"events": [shared_event]},  # same event in 2nd category
                ],
            }
        ]
    }
    entries = m.extract_stats_from_gamelog(sample_gamelog)
    assert len(entries) == 1, f"Duplicate event not deduplicated — got {len(entries)} entries"


def test_gamelog_fallback_has_season_label():
    """Fallback path (flat 'events' list) must also tag entries with season_label."""
    sample = {
        "events": [
            {
                "date": "2025-09-07",
                "opponent": {"displayName": "Tampa Bay Buccaneers"},
                "stats": [],
            }
        ]
    }
    entries = m.extract_stats_from_gamelog(sample)
    assert entries, "Expected at least one fallback entry"
    for entry in entries:
        assert "season_label" in entry


# ---------------------------------------------------------------------------
# 6. build_live_game_embed produces a valid Discord Embed
# ---------------------------------------------------------------------------

def test_build_live_game_embed_in_progress():
    """build_live_game_embed must return a red embed for live games."""
    game = {
        "id": "401547417",
        "name": "MIA @ BUF",
        "away_team": "MIA",
        "away_name": "Miami Dolphins",
        "home_team": "BUF",
        "home_name": "Buffalo Bills",
        "away_score": "17",
        "home_score": "14",
        "state": "3rd - 8:42",
        "in_progress": True,
        "completed": False,
        "down_distance": "2nd & 7",
    }
    embed = m.build_live_game_embed(game, {})
    assert isinstance(embed, discord.Embed)
    assert "LIVE" in (embed.description or "")
    assert embed.color.value == 0xD62828


def test_build_live_game_embed_final():
    """build_live_game_embed must return a normal embed for final games."""
    game = {
        "id": "401547418",
        "name": "KC @ LV",
        "away_team": "KC",
        "away_name": "Kansas City Chiefs",
        "home_team": "LV",
        "home_name": "Las Vegas Raiders",
        "away_score": "24",
        "home_score": "17",
        "state": "Final",
        "in_progress": False,
        "completed": True,
        "down_distance": "",
    }
    embed = m.build_live_game_embed(game, {})
    assert isinstance(embed, discord.Embed)
    assert "Final" in (embed.description or "")
    assert embed.color.value == 0x7A5C2E


def test_build_live_game_embed_with_summary():
    """build_live_game_embed should include leader stats when summary has them."""
    game = {
        "id": "123",
        "name": "DAL @ PHI",
        "away_team": "DAL",
        "away_name": "Dallas Cowboys",
        "home_team": "PHI",
        "home_name": "Philadelphia Eagles",
        "away_score": "10",
        "home_score": "20",
        "state": "4th - 2:15",
        "in_progress": True,
        "completed": False,
        "down_distance": "3rd & 5",
    }
    summary = {
        "leaders": [
            {
                "displayName": "Passing Yards",
                "leaders": [
                    {
                        "athlete": {"displayName": "Dak Prescott"},
                        "displayValue": "215 YDS, 1 TD, 0 INT",
                    }
                ],
            }
        ]
    }
    embed = m.build_live_game_embed(game, summary)
    assert any(
        f.name == "Passing Yards" for f in embed.fields
    ), "Expected 'Passing Yards' field in embed"
    assert any(
        "Dak Prescott" in f.value for f in embed.fields
    ), "Expected athlete name in field value"


# ---------------------------------------------------------------------------
# 7. AI personality source-confidentiality rules are present
# ---------------------------------------------------------------------------

from ai.personalities import SECURITY_RULES, HARD_RULES


def test_security_rules_has_nfl_source_protection():
    """SECURITY_RULES must contain NFL data source confidentiality guidance."""
    assert "NFL Data Sources" in SECURITY_RULES, (
        "SECURITY_RULES is missing the NFL Data Sources confidentiality section"
    )


def test_security_rules_no_espn_in_generic_response():
    """The generic response template in SECURITY_RULES must not name ESPN."""
    # The rule should say "configured NFL data services" not "ESPN"
    assert "configured NFL data services" in SECURITY_RULES


def test_hard_rules_no_live_espn_reference():
    """HARD_RULES must not reference 'ESPN' as the live-data provider."""
    assert "live ESPN" not in HARD_RULES, (
        "HARD_RULES reveals ESPN as the live-data provider — use generic wording"
    )
