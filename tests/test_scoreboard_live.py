"""
Tests for ScoreboardView live-game path and team-filter Select.

Covers the scenarios that only appear when week-1 (or any regular-season week)
games are in progress — simulated here via synthetic game fixtures so the suite
can run without a live ESPN connection.

Scenarios verified:
  1. _rebuild() adds the 🔴 live-game Select (row 3) only when in_progress games exist.
  2. _rebuild() omits row 3 entirely when no games are live.
  3. Team-filter Select options carry the correct status icon per game state.
  4. Team-filter correctly isolates a single game (same logic as _on_team_select).
  5. build_live_game_embed includes boxscore team stats when the summary has them.
  6. build_live_game_embed footer carries LIVE marker when game is in progress.
  7. LiveGameView and _TeamGameView are constructable and hold their parent reference.
  8. build_live_game_embed handles a completely empty summary without raising.
  9. Live-game Select option label carries the 🔴 prefix and score description.
 10. Refreshed _rebuild() picks up a newly-live game that wasn't live at first build.
"""

import discord
import pytest
import main as m


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _make_game(
    game_id: str,
    away: str,
    home: str,
    a_score: str = "0",
    h_score: str = "0",
    state: str = "10:00 AM ET",
    in_progress: bool = False,
    completed: bool = False,
    down_distance: str = "",
) -> dict:
    return {
        "id": game_id,
        "name": f"{away} @ {home}",
        "away_team": away,
        "away_name": m.TEAM_NAMES.get(away, away),
        "home_team": home,
        "home_name": m.TEAM_NAMES.get(home, home),
        "away_score": a_score,
        "home_score": h_score,
        "state": state,
        "in_progress": in_progress,
        "completed": completed,
        "down_distance": down_distance,
        "away_winner": False,
        "home_winner": False,
        "away_record": "",
        "home_record": "",
        "possession": None,
    }


_META = {
    "year": 2026,
    "season_type": 2,
    "type_name": "Regular Season",
    "week": 1,
    "week_label": "Week 1",
    "max_week": 18,
    "display": "Regular Season • Week 1 • 2025/2026",
}


def _live_game() -> dict:
    return _make_game(
        "401547100", "KC", "PHI",
        a_score="14", h_score="21",
        state="2nd - 4:33",
        in_progress=True,
        down_distance="1st & 10",
    )


def _scheduled_game() -> dict:
    return _make_game("401547101", "DAL", "NYG", state="4:25 PM ET")


def _final_game() -> dict:
    return _make_game(
        "401547102", "BUF", "MIA",
        a_score="30", h_score="24",
        state="Final",
        completed=True,
    )


# ---------------------------------------------------------------------------
# 1. row-3 live-game Select appears when at least one game is in_progress
# ---------------------------------------------------------------------------

def test_rebuild_adds_live_select_when_game_in_progress():
    """ScoreboardView must add a row-3 Select when any game is in_progress."""
    games = [_live_game(), _scheduled_game()]
    view = m.ScoreboardView(games, dict(_META))

    selects = [c for c in view.children if isinstance(c, discord.ui.Select)]
    live_selects = [s for s in selects if s.row == 3]
    assert live_selects, "Expected a row-3 live-game Select when games are in_progress"
    assert live_selects[0].placeholder == "🔴 View a live game…"


# ---------------------------------------------------------------------------
# 2. row-3 live-game Select is absent when no games are in_progress
# ---------------------------------------------------------------------------

def test_rebuild_omits_live_select_when_no_game_in_progress():
    """ScoreboardView must NOT add a row-3 Select when all games are finished/scheduled."""
    games = [_scheduled_game(), _final_game()]
    view = m.ScoreboardView(games, dict(_META))

    selects = [c for c in view.children if isinstance(c, discord.ui.Select)]
    live_selects = [s for s in selects if s.row == 3]
    assert not live_selects, "Row-3 live-game Select must be absent when no games are live"


# ---------------------------------------------------------------------------
# 3. Team-filter Select uses correct status icons per game state
# ---------------------------------------------------------------------------

def test_team_filter_icons_correct():
    """Team-filter options must use 🔴 (live), ✅ (final), 🕐 (scheduled)."""
    games = [_live_game(), _final_game(), _scheduled_game()]
    view = m.ScoreboardView(games, dict(_META))

    team_sel = next(
        (c for c in view.children if isinstance(c, discord.ui.Select) and c.row == 2),
        None,
    )
    assert team_sel is not None, "Row-2 team-filter Select must exist"

    labels_by_value = {opt.value: opt.label for opt in team_sel.options}

    # KC and PHI are in the live game — should carry 🔴
    assert labels_by_value.get("KC", "").startswith("🔴"), f"KC label should start with 🔴: {labels_by_value.get('KC')}"
    assert labels_by_value.get("PHI", "").startswith("🔴"), f"PHI label should start with 🔴: {labels_by_value.get('PHI')}"

    # BUF and MIA are in the final game — should carry ✅
    assert labels_by_value.get("BUF", "").startswith("✅"), f"BUF label should start with ✅: {labels_by_value.get('BUF')}"
    assert labels_by_value.get("MIA", "").startswith("✅"), f"MIA label should start with ✅: {labels_by_value.get('MIA')}"

    # DAL and NYG are scheduled — should carry 🕐
    assert labels_by_value.get("DAL", "").startswith("🕐"), f"DAL label should start with 🕐: {labels_by_value.get('DAL')}"
    assert labels_by_value.get("NYG", "").startswith("🕐"), f"NYG label should start with 🕐: {labels_by_value.get('NYG')}"


# ---------------------------------------------------------------------------
# 4. Team filter correctly isolates the matching game
# ---------------------------------------------------------------------------

def test_team_filter_isolates_correct_game():
    """Filtering by team abbr must return exactly the game containing that team."""
    live = _live_game()
    scheduled = _scheduled_game()
    games = [live, scheduled]

    # Replicate the _on_team_select filter logic directly
    team_abbr = "KC"
    team_games = [g for g in games if team_abbr in (g["away_team"], g["home_team"])]
    assert len(team_games) == 1
    assert team_games[0]["id"] == live["id"]

    # DAL should resolve to the scheduled game
    team_games_dal = [g for g in games if "DAL" in (g["away_team"], g["home_team"])]
    assert len(team_games_dal) == 1
    assert team_games_dal[0]["id"] == scheduled["id"]


# ---------------------------------------------------------------------------
# 5. build_live_game_embed includes boxscore team stats from summary
# ---------------------------------------------------------------------------

def test_build_live_game_embed_boxscore_stats():
    """Team stats from summary['boxscore']['teams'] must appear as embed fields."""
    game = _live_game()
    summary = {
        "boxscore": {
            "teams": [
                {
                    "team": {"abbreviation": "KC"},
                    "statistics": [
                        {"displayName": "Total Yards", "displayValue": "312"},
                        {"displayName": "Passing Yards", "displayValue": "248"},
                    ],
                },
                {
                    "team": {"abbreviation": "PHI"},
                    "statistics": [
                        {"displayName": "Total Yards", "displayValue": "289"},
                    ],
                },
            ]
        }
    }
    embed = m.build_live_game_embed(game, summary)

    field_names = [f.name for f in embed.fields]
    assert any("KC" in n for n in field_names), "Expected KC team stats field"
    assert any("PHI" in n for n in field_names), "Expected PHI team stats field"

    # Stat values must appear in the field text
    all_values = " ".join(f.value for f in embed.fields)
    assert "Total Yards" in all_values
    assert "312" in all_values


# ---------------------------------------------------------------------------
# 6. build_live_game_embed footer carries LIVE marker for in-progress game
# ---------------------------------------------------------------------------

def test_build_live_game_embed_footer_live():
    """Footer must contain 'LIVE' for an in-progress game and plain 'Uce' for final."""
    live_embed = m.build_live_game_embed(_live_game(), {})
    assert live_embed.footer is not None
    assert "LIVE" in (live_embed.footer.text or "")

    final_embed = m.build_live_game_embed(_final_game(), {})
    assert "LIVE" not in (final_embed.footer.text or "")


# ---------------------------------------------------------------------------
# 7. LiveGameView and _TeamGameView hold correct parent reference
# ---------------------------------------------------------------------------

def test_live_game_view_holds_parent():
    """LiveGameView must store both the game and its parent ScoreboardView."""
    parent = m.ScoreboardView([_live_game()], dict(_META))
    lgv = m.LiveGameView(_live_game(), parent)

    assert lgv.parent is parent
    assert lgv.game["id"] == "401547100"


def test_team_game_view_holds_parent():
    """_TeamGameView must store both the game and its parent ScoreboardView."""
    parent = m.ScoreboardView([_final_game()], dict(_META))
    tgv = m._TeamGameView(_final_game(), parent)

    assert tgv.parent is parent
    assert tgv.game["id"] == "401547102"


# ---------------------------------------------------------------------------
# 8. build_live_game_embed handles empty summary without raising
# ---------------------------------------------------------------------------

def test_build_live_game_embed_empty_summary():
    """build_live_game_embed must not raise when summary is empty or missing keys."""
    embed = m.build_live_game_embed(_live_game(), {})
    assert isinstance(embed, discord.Embed)

    embed2 = m.build_live_game_embed(_live_game(), {"leaders": [], "boxscore": {}})
    assert isinstance(embed2, discord.Embed)


# ---------------------------------------------------------------------------
# 9. Live-game Select option label and description format
# ---------------------------------------------------------------------------

def test_live_select_option_format():
    """Row-3 live-game Select options must carry 🔴 prefix and score as description."""
    live = _live_game()
    view = m.ScoreboardView([live], dict(_META))

    live_sel = next(
        (c for c in view.children if isinstance(c, discord.ui.Select) and c.row == 3),
        None,
    )
    assert live_sel is not None

    opt = live_sel.options[0]
    assert opt.value == live["id"], "Option value must be the game ID"
    assert opt.label.startswith("🔴"), f"Live option label must start with 🔴, got: {opt.label!r}"
    # Description should contain both scores
    assert live["away_score"] in (opt.description or "")
    assert live["home_score"] in (opt.description or "")


# ---------------------------------------------------------------------------
# 10. _rebuild() picks up a newly-live game after state mutates
# ---------------------------------------------------------------------------

def test_rebuild_detects_newly_live_game():
    """After mutating a game to in_progress, calling _rebuild() must add row-3 Select."""
    game = _scheduled_game()
    view = m.ScoreboardView([game], dict(_META))

    # Confirm no live select initially
    assert not any(
        isinstance(c, discord.ui.Select) and c.row == 3 for c in view.children
    ), "Should have no live select before any game goes live"

    # Simulate the game going live
    game["in_progress"] = True
    game["state"] = "1st - 12:30"
    game["away_score"] = "0"
    game["home_score"] = "0"
    view.games = [game]
    view._rebuild()

    assert any(
        isinstance(c, discord.ui.Select) and c.row == 3 for c in view.children
    ), "_rebuild() must add live Select after a game transitions to in_progress"
