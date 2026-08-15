"""
Tests for the independent live game tracker system.

NOTE: August 15 = NFL preseason with no live games available, so all tests
here are unit/mock-only — no live Discord or ESPN API calls are made.

Covers:
  - TrackerState fields and registry isolation
  - _stop_tracker behaviour (removes from registry, sets active=False, cancels task)
  - Multiple-tracker independence (stopping one leaves the others untouched)
  - _build_tracker_embed for live / final / empty-game cases
  - _build_all_games_tracker_embed with mixed game states
  - _run_single_game_tracker self-terminates on game-final
  - _run_single_game_tracker cleans up on discord.NotFound
  - _run_all_games_tracker stops when all games are concluded
  - Tracker isolation across background tasks
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

import main as m


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mk_state(tracker_id="t1", game_id="g1", channel_id=111, owner_id=42, message_id=999):
    return m.TrackerState(
        tracker_id=tracker_id,
        game_id=game_id,
        channel_id=channel_id,
        guild_id=1,
        owner_id=owner_id,
        message_id=message_id,
    )


def _live_game(gid="g1", **over):
    g = {
        "id": gid,
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
    g.update(over)
    return g


def _final_game(gid="g1", **over):
    return _live_game(gid, in_progress=False, completed=True, state="Final", **over)


def _scheduled_game(gid="g3", **over):
    return _live_game(gid, in_progress=False, completed=False, state="Sun 1:00 PM", **over)


@pytest.fixture(autouse=True)
def _clean_registry():
    m._LIVE_TRACKERS.clear()
    yield
    m._LIVE_TRACKERS.clear()


# ---------------------------------------------------------------------------
# 1. TrackerState + registry
# ---------------------------------------------------------------------------

def test_tracker_state_fields():
    s = _mk_state()
    assert s.tracker_id == "t1"
    assert s.game_id == "g1"
    assert s.channel_id == 111
    assert s.owner_id == 42
    assert s.message_id == 999
    assert s.active is True
    assert s.concluded_game_ids == set()
    assert s.task is None


def test_tracker_state_all_games_variant():
    s = m.TrackerState(tracker_id="t2", game_id=None, channel_id=1, guild_id=None, owner_id=7)
    assert s.game_id is None
    assert s.message_id is None


def test_registry_isolation():
    a, b = _mk_state("a"), _mk_state("b", game_id="g2")
    m._LIVE_TRACKERS["a"] = a
    m._LIVE_TRACKERS["b"] = b
    a.concluded_game_ids.add("x")
    assert b.concluded_game_ids == set(), "concluded_game_ids must not be shared between trackers"


# ---------------------------------------------------------------------------
# 2. _stop_tracker
# ---------------------------------------------------------------------------

def test_stop_tracker_removes_and_deactivates():
    s = _mk_state("t1")
    m._LIVE_TRACKERS["t1"] = s
    m._stop_tracker("t1")
    assert "t1" not in m._LIVE_TRACKERS
    assert s.active is False


def test_stop_tracker_cancels_task():
    async def run():
        s = _mk_state("t1")
        s.task = asyncio.create_task(asyncio.sleep(60))
        m._LIVE_TRACKERS["t1"] = s
        m._stop_tracker("t1")
        await asyncio.sleep(0)
        assert s.task.cancelled() or s.task.cancelling()
        s.task.cancel()
    asyncio.run(run())


def test_stop_tracker_missing_id_noop():
    m._stop_tracker("does-not-exist")  # must not raise


def test_multiple_tracker_independence():
    a, b, c = _mk_state("a"), _mk_state("b", game_id="g2"), _mk_state("c", game_id="g3")
    for s in (a, b, c):
        m._LIVE_TRACKERS[s.tracker_id] = s
    m._stop_tracker("a")
    assert a.active is False
    assert "a" not in m._LIVE_TRACKERS
    assert m._LIVE_TRACKERS["b"] is b and b.active
    assert m._LIVE_TRACKERS["c"] is c and c.active


# ---------------------------------------------------------------------------
# 3. _is_game_final
# ---------------------------------------------------------------------------

def test_is_game_final():
    assert m._is_game_final(_final_game())
    assert not m._is_game_final(_live_game())
    assert not m._is_game_final(_scheduled_game())


# ---------------------------------------------------------------------------
# 4. _build_tracker_embed
# ---------------------------------------------------------------------------

def test_tracker_embed_live():
    e = m._build_tracker_embed(_live_game(), {}, "1:00 PM ET")
    assert isinstance(e, discord.Embed)
    assert "LIVE" in e.description
    assert "Miami Dolphins" in e.description
    assert e.color.value == 0xD62828
    assert "Auto-updates every 5 min" in e.footer.text


def test_tracker_embed_final():
    e = m._build_tracker_embed(_final_game(), {}, "4:00 PM ET", final=True)
    assert "🏁" in e.description and "FINAL" in e.description
    assert e.color.value == 0x7A5C2E
    assert "tracking ended" in e.footer.text


def test_tracker_embed_empty_game():
    e = m._build_tracker_embed({}, {}, "1:00 PM ET")
    assert isinstance(e, discord.Embed)
    assert "Away" in e.title and "Home" in e.title


def test_tracker_embed_leaders():
    summary = {
        "leaders": [
            {"displayName": "Passing Yards",
             "leaders": [{"athlete": {"displayName": "Tua"}, "displayValue": "250 YDS"}]},
        ]
    }
    e = m._build_tracker_embed(_live_game(), summary, "1:00 PM ET")
    assert any(f.name == "Passing Yards" and "Tua" in f.value for f in e.fields)


# ---------------------------------------------------------------------------
# 5. _build_all_games_tracker_embed
# ---------------------------------------------------------------------------

def test_all_games_embed_mixed():
    games = [_live_game("g1"), _final_game("g2", away_team="KC", home_team="LV"),
             _scheduled_game("g3", away_team="DAL", home_team="PHI")]
    e = m._build_all_games_tracker_embed(games, "1:00 PM ET")
    assert "🔴" in e.description
    assert "✅ FINAL" in e.description
    assert "🕐" in e.description
    assert e.color.value == 0xD62828


def test_all_games_embed_all_final():
    games = [_final_game("g1"), _final_game("g2")]
    e = m._build_all_games_tracker_embed(games, "11:00 PM ET")
    assert e.color.value == 0x7A5C2E
    assert "All games final" in e.footer.text


def test_all_games_embed_empty():
    e = m._build_all_games_tracker_embed([], "1:00 PM ET")
    assert "No games found" in e.description


# ---------------------------------------------------------------------------
# 6. Background task behaviour (async mocks; sleep patched to be instant)
# ---------------------------------------------------------------------------

def _mock_channel_message():
    message = AsyncMock()
    channel = MagicMock()
    channel.fetch_message = AsyncMock(return_value=message)
    return channel, message


def test_single_tracker_stops_on_final():
    async def run():
        s = _mk_state("t1")
        m._LIVE_TRACKERS["t1"] = s
        channel, message = _mock_channel_message()
        with patch.object(m.asyncio, "sleep", AsyncMock()), \
             patch.object(m, "_fetch_tracker_data", AsyncMock(return_value=(_final_game(), {}))), \
             patch.object(m.bot, "get_channel", return_value=channel):
            await asyncio.wait_for(m._run_single_game_tracker("t1"), timeout=5)
        assert "t1" not in m._LIVE_TRACKERS
        assert s.active is False
        message.edit.assert_awaited()
        embed = message.edit.await_args.kwargs["embed"]
        assert "FINAL" in embed.description
    asyncio.run(run())


def test_single_tracker_cleans_up_on_notfound():
    async def run():
        s = _mk_state("t1")
        m._LIVE_TRACKERS["t1"] = s
        channel = MagicMock()
        channel.fetch_message = AsyncMock(
            side_effect=discord.NotFound(MagicMock(status=404), "gone")
        )
        with patch.object(m.asyncio, "sleep", AsyncMock()), \
             patch.object(m, "_fetch_tracker_data", AsyncMock(return_value=(_live_game(), {}))), \
             patch.object(m.bot, "get_channel", return_value=channel):
            await asyncio.wait_for(m._run_single_game_tracker("t1"), timeout=5)
        assert "t1" not in m._LIVE_TRACKERS
        assert s.active is False
    asyncio.run(run())


def test_single_tracker_exits_when_registry_cleared():
    async def run():
        # Not in registry at all → returns immediately on first wake
        with patch.object(m.asyncio, "sleep", AsyncMock()):
            await asyncio.wait_for(m._run_single_game_tracker("ghost"), timeout=5)
    asyncio.run(run())


def test_all_games_tracker_stops_when_all_concluded():
    async def run():
        s = m.TrackerState(tracker_id="all", game_id=None, channel_id=1,
                           guild_id=1, owner_id=42, message_id=9)
        m._LIVE_TRACKERS["all"] = s
        channel, message = _mock_channel_message()
        games = [_final_game("g1"), _final_game("g2")]
        with patch.object(m.asyncio, "sleep", AsyncMock()), \
             patch.object(m, "get_scoreboard_data", AsyncMock(return_value=(games, {}))), \
             patch.object(m.bot, "get_channel", return_value=channel):
            await asyncio.wait_for(m._run_all_games_tracker("all"), timeout=5)
        assert "all" not in m._LIVE_TRACKERS
        assert s.active is False
        assert s.concluded_game_ids == {"g1", "g2"}
        message.edit.assert_awaited()
    asyncio.run(run())


def test_tracker_isolation_across_tasks():
    """Game finishing in tracker B must not touch tracker A."""
    async def run():
        a = _mk_state("a", game_id="gA")
        b = _mk_state("b", game_id="gB")
        m._LIVE_TRACKERS["a"] = a
        m._LIVE_TRACKERS["b"] = b
        channel, _ = _mock_channel_message()

        async def fetch(state):
            if state.game_id == "gB":
                return _final_game("gB"), {}
            return _live_game("gA"), {}

        with patch.object(m.asyncio, "sleep", AsyncMock()), \
             patch.object(m, "_fetch_tracker_data", AsyncMock(side_effect=fetch)), \
             patch.object(m.bot, "get_channel", return_value=channel):
            # Run B to completion (its game is final)
            await asyncio.wait_for(m._run_single_game_tracker("b"), timeout=5)
        assert "b" not in m._LIVE_TRACKERS and b.active is False
        assert m._LIVE_TRACKERS["a"] is a and a.active is True
    asyncio.run(run())


# ---------------------------------------------------------------------------
# 7. Views & auth
# ---------------------------------------------------------------------------

def test_tracker_views_have_no_timeout():
    v1 = m.LiveTrackerView("t1")
    v2 = m.AllGamesTrackerView("t2")
    assert v1.timeout is None
    assert v2.timeout is None


def test_tracker_views_have_expected_buttons():
    for cls in (m.LiveTrackerView, m.AllGamesTrackerView):
        v = cls("x")
        labels = {item.label for item in v.children}
        assert "🔄 Update Now" in labels
        assert "🛑 End Tracking" in labels


def test_tracker_auth_owner_admin_and_denied():
    def mk_inter(user_id, admin=False, manage=False):
        inter = MagicMock()
        inter.user.id = user_id
        inter.user.guild_permissions.administrator = admin
        inter.user.guild_permissions.manage_guild = manage
        return inter

    assert m._tracker_auth_ok(mk_inter(42), 42)                       # owner
    assert m._tracker_auth_ok(mk_inter(7, admin=True), 42)            # admin
    assert m._tracker_auth_ok(mk_inter(7, manage=True), 42)           # manage_guild
    assert not m._tracker_auth_ok(mk_inter(7), 42)                    # random user


# ---------------------------------------------------------------------------
# 8. Wiring: scoreboard command & view accept destination/owner
# ---------------------------------------------------------------------------

def test_scoreboard_view_accepts_dest_and_owner():
    v = m.ScoreboardView([], {"week": 1, "max_week": 18, "season_type": 2, "year": 2026},
                         dest_channel_id=123, owner_id=42)
    assert v.dest_channel_id == 123
    assert v.owner_id == 42


def test_scoreboard_track_all_button_only_with_live_games():
    meta = {"week": 1, "max_week": 18, "season_type": 2, "year": 2026}
    v_live = m.ScoreboardView([_live_game()], meta)
    labels = {getattr(i, "label", None) for i in v_live.children}
    assert "📡 Track All Live Games" in labels

    v_none = m.ScoreboardView([_final_game()], meta)
    labels = {getattr(i, "label", None) for i in v_none.children}
    assert "📡 Track All Live Games" not in labels


def _mk_click_interaction(user_id, channel):
    inter = MagicMock()
    inter.user.id = user_id
    inter.guild_id = 1
    inter.channel = channel
    inter.data = {"values": ["g1"]}
    inter.response.defer = AsyncMock()
    inter.followup.send = AsyncMock()
    return inter


def test_single_tracker_owner_is_clicker_not_scoreboard_poster():
    """A tracker started from someone else's scoreboard belongs to the clicker."""
    async def run():
        meta = {"week": 1, "max_week": 18, "season_type": 2, "year": 2026}
        view = m.ScoreboardView([_live_game("g1")], meta,
                                dest_channel_id=None, owner_id=100)  # poster = 100
        channel = MagicMock()
        channel.id = 555
        channel.mention = "#scores"
        message = MagicMock(id=777)
        channel.send = AsyncMock(return_value=message)
        inter = _mk_click_interaction(user_id=200, channel=channel)  # clicker = 200

        with patch.object(m, "get_game_summary", AsyncMock(return_value={})), \
             patch.object(m.asyncio, "create_task", lambda coro: (coro.close(), MagicMock())[1]):
            await view._on_live_game_select(inter)

        states = list(m._LIVE_TRACKERS.values())
        assert len(states) == 1
        assert states[0].owner_id == 200, "Tracker owner must be the clicker, not the scoreboard poster"
        # Clicker can end it; poster (non-admin) cannot
        def mk(uid):
            i = MagicMock()
            i.user.id = uid
            i.user.guild_permissions.administrator = False
            i.user.guild_permissions.manage_guild = False
            return i
        assert m._tracker_auth_ok(mk(200), states[0].owner_id)
        assert not m._tracker_auth_ok(mk(100), states[0].owner_id)
    asyncio.run(run())


def test_all_games_tracker_owner_is_clicker_not_scoreboard_poster():
    async def run():
        meta = {"week": 1, "max_week": 18, "season_type": 2, "year": 2026}
        view = m.ScoreboardView([_live_game("g1")], meta,
                                dest_channel_id=None, owner_id=100)
        channel = MagicMock()
        channel.id = 555
        channel.mention = "#scores"
        message = MagicMock(id=778)
        channel.send = AsyncMock(return_value=message)
        inter = _mk_click_interaction(user_id=300, channel=channel)

        with patch.object(m, "get_scoreboard_data", AsyncMock(return_value=([_live_game("g1")], meta))), \
             patch.object(m.asyncio, "create_task", lambda coro: (coro.close(), MagicMock())[1]):
            await view._track_all_live_games(inter)

        states = list(m._LIVE_TRACKERS.values())
        assert len(states) == 1
        assert states[0].owner_id == 300
    asyncio.run(run())


def test_scoreboard_command_has_channel_param():
    import pathlib
    src = pathlib.Path("main.py").read_text(encoding="utf-8")
    assert "async def scoreboard(interaction: discord.Interaction, channel: discord.TextChannel | None = None)" in src


# ---------------------------------------------------------------------------
# 9. Per-guild cap and duplicate detection
# ---------------------------------------------------------------------------

def test_guild_tracker_count_empty():
    assert m._guild_tracker_count(1) == 0


def test_guild_tracker_count_only_counts_target_guild():
    m._LIVE_TRACKERS["a"] = _mk_state("a", channel_id=1)   # guild_id=1 (from helper)
    m._LIVE_TRACKERS["b"] = _mk_state("b", channel_id=2)   # guild_id=1
    # Add a tracker for a different guild
    other = m.TrackerState(tracker_id="c", game_id="g3", channel_id=3, guild_id=99, owner_id=5)
    m._LIVE_TRACKERS["c"] = other
    assert m._guild_tracker_count(1) == 2
    assert m._guild_tracker_count(99) == 1
    assert m._guild_tracker_count(2) == 0


def test_guild_tracker_count_none_guild():
    # guild_id=None (DMs) always returns 0 to avoid blocking DM usage
    assert m._guild_tracker_count(None) == 0


def test_find_duplicate_tracker_no_match():
    m._LIVE_TRACKERS["t1"] = _mk_state("t1", game_id="g1", channel_id=111)
    assert m._find_duplicate_tracker(guild_id=1, channel_id=222, game_id="g1") is None  # different channel
    assert m._find_duplicate_tracker(guild_id=2, channel_id=111, game_id="g1") is None  # different guild


def test_find_duplicate_tracker_match():
    s = _mk_state("t1", game_id="g1", channel_id=111)
    m._LIVE_TRACKERS["t1"] = s
    found = m._find_duplicate_tracker(guild_id=1, channel_id=111, game_id="g1")
    assert found is s


def test_find_duplicate_all_games_tracker():
    s = m.TrackerState(tracker_id="all", game_id=None, channel_id=555, guild_id=1, owner_id=7)
    m._LIVE_TRACKERS["all"] = s
    assert m._find_duplicate_tracker(guild_id=1, channel_id=555, game_id=None) is s
    assert m._find_duplicate_tracker(guild_id=1, channel_id=555, game_id="g1") is None  # different game_id


def _mk_click_interaction_with_guild(user_id, channel, guild_id=1):
    inter = MagicMock()
    inter.user.id = user_id
    inter.guild_id = guild_id
    inter.channel = channel
    inter.data = {"values": ["g1"]}
    inter.response.defer = AsyncMock()
    inter.followup.send = AsyncMock()
    return inter


def _make_channel(cid=555):
    channel = MagicMock()
    channel.id = cid
    channel.mention = f"#ch{cid}"
    channel.send = AsyncMock(return_value=MagicMock(id=999))
    return channel


def test_single_tracker_blocked_at_guild_cap():
    """Starting a 6th tracker in a guild returns an ephemeral error, no new tracker created."""
    async def run():
        # Fill the guild up to the cap
        for i in range(m._MAX_TRACKERS_PER_GUILD):
            s = m.TrackerState(
                tracker_id=f"existing-{i}", game_id=f"gx{i}",
                channel_id=100 + i, guild_id=1, owner_id=1,
            )
            m._LIVE_TRACKERS[f"existing-{i}"] = s

        meta = {"week": 1, "max_week": 18, "season_type": 2, "year": 2026}
        view = m.ScoreboardView([_live_game("g1")], meta, dest_channel_id=None, owner_id=100)
        channel = _make_channel(999)
        inter = _mk_click_interaction_with_guild(user_id=200, channel=channel, guild_id=1)

        with patch.object(m, "get_game_summary", AsyncMock(return_value={})), \
             patch.object(m.asyncio, "create_task", lambda coro: (coro.close(), MagicMock())[1]):
            await view._on_live_game_select(inter)

        # No new tracker should have been added
        guild_trackers = [s for s in m._LIVE_TRACKERS.values() if s.guild_id == 1]
        assert len(guild_trackers) == m._MAX_TRACKERS_PER_GUILD
        inter.followup.send.assert_awaited_once()
        msg = inter.followup.send.await_args.args[0]
        assert "maximum" in msg.lower() or "active trackers" in msg.lower()
    asyncio.run(run())


def test_single_tracker_blocked_on_duplicate():
    """Starting a tracker for a game already tracked in the same channel is rejected."""
    async def run():
        existing = _mk_state("dup", game_id="g1", channel_id=555)
        m._LIVE_TRACKERS["dup"] = existing

        meta = {"week": 1, "max_week": 18, "season_type": 2, "year": 2026}
        view = m.ScoreboardView([_live_game("g1")], meta, dest_channel_id=None, owner_id=100)
        channel = _make_channel(555)
        inter = _mk_click_interaction_with_guild(user_id=200, channel=channel, guild_id=1)

        with patch.object(m, "get_game_summary", AsyncMock(return_value={})), \
             patch.object(m.asyncio, "create_task", lambda coro: (coro.close(), MagicMock())[1]):
            await view._on_live_game_select(inter)

        # Registry still has only the one original tracker
        assert len(m._LIVE_TRACKERS) == 1
        assert "dup" in m._LIVE_TRACKERS
        inter.followup.send.assert_awaited_once()
        msg = inter.followup.send.await_args.args[0]
        assert "already" in msg.lower()
    asyncio.run(run())


def test_all_games_tracker_blocked_at_guild_cap():
    """📡 Track All is rejected when the guild is at the cap."""
    async def run():
        for i in range(m._MAX_TRACKERS_PER_GUILD):
            s = m.TrackerState(
                tracker_id=f"ex-{i}", game_id=f"gx{i}",
                channel_id=200 + i, guild_id=1, owner_id=1,
            )
            m._LIVE_TRACKERS[f"ex-{i}"] = s

        meta = {"week": 1, "max_week": 18, "season_type": 2, "year": 2026}
        view = m.ScoreboardView([_live_game("g1")], meta, dest_channel_id=None, owner_id=100)
        channel = _make_channel(888)
        inter = _mk_click_interaction_with_guild(user_id=300, channel=channel, guild_id=1)

        with patch.object(m, "get_scoreboard_data", AsyncMock(return_value=([_live_game("g1")], meta))), \
             patch.object(m.asyncio, "create_task", lambda coro: (coro.close(), MagicMock())[1]):
            await view._track_all_live_games(inter)

        guild_trackers = [s for s in m._LIVE_TRACKERS.values() if s.guild_id == 1]
        assert len(guild_trackers) == m._MAX_TRACKERS_PER_GUILD
        inter.followup.send.assert_awaited_once()
        msg = inter.followup.send.await_args.args[0]
        assert "maximum" in msg.lower() or "active trackers" in msg.lower()
    asyncio.run(run())


def test_all_games_tracker_blocked_on_duplicate():
    """A second all-games tracker in the same channel is rejected."""
    async def run():
        existing = m.TrackerState(
            tracker_id="all-dup", game_id=None, channel_id=555, guild_id=1, owner_id=7
        )
        m._LIVE_TRACKERS["all-dup"] = existing

        meta = {"week": 1, "max_week": 18, "season_type": 2, "year": 2026}
        view = m.ScoreboardView([_live_game("g1")], meta, dest_channel_id=None, owner_id=100)
        channel = _make_channel(555)
        inter = _mk_click_interaction_with_guild(user_id=300, channel=channel, guild_id=1)

        with patch.object(m, "get_scoreboard_data", AsyncMock(return_value=([_live_game("g1")], meta))), \
             patch.object(m.asyncio, "create_task", lambda coro: (coro.close(), MagicMock())[1]):
            await view._track_all_live_games(inter)

        assert len(m._LIVE_TRACKERS) == 1
        assert "all-dup" in m._LIVE_TRACKERS
        inter.followup.send.assert_awaited_once()
        msg = inter.followup.send.await_args.args[0]
        assert "already" in msg.lower()
    asyncio.run(run())


def test_tracker_allowed_when_below_cap():
    """A tracker for a different game in a different channel is allowed when below the cap."""
    async def run():
        # 4 existing trackers (below cap of 5)
        for i in range(m._MAX_TRACKERS_PER_GUILD - 1):
            s = m.TrackerState(
                tracker_id=f"ok-{i}", game_id=f"gx{i}",
                channel_id=300 + i, guild_id=1, owner_id=1,
            )
            m._LIVE_TRACKERS[f"ok-{i}"] = s

        meta = {"week": 1, "max_week": 18, "season_type": 2, "year": 2026}
        view = m.ScoreboardView([_live_game("g1")], meta, dest_channel_id=None, owner_id=100)
        channel = _make_channel(999)
        inter = _mk_click_interaction_with_guild(user_id=200, channel=channel, guild_id=1)

        with patch.object(m, "get_game_summary", AsyncMock(return_value={})), \
             patch.object(m.asyncio, "create_task", lambda coro: (coro.close(), MagicMock())[1]):
            await view._on_live_game_select(inter)

        guild_trackers = [s for s in m._LIVE_TRACKERS.values() if s.guild_id == 1]
        assert len(guild_trackers) == m._MAX_TRACKERS_PER_GUILD
    asyncio.run(run())


# ---------------------------------------------------------------------------
# 10. Concurrent race-condition tests (atomic reservation)
# ---------------------------------------------------------------------------

def test_concurrent_single_trackers_respect_guild_cap():
    """Firing N simultaneous tracker starts (N > cap) must leave at most cap trackers."""
    async def run():
        meta = {"week": 1, "max_week": 18, "season_type": 2, "year": 2026}
        cap = m._MAX_TRACKERS_PER_GUILD
        # Simulate (cap + 2) concurrent clicks on different games, each with a
        # slow get_game_summary that yields to the event loop before returning.
        async def slow_summary(*_a, **_kw):
            await asyncio.sleep(0)  # yield — lets other coroutines advance
            return {}

        views_and_inters = []
        for i in range(cap + 2):
            game = _live_game(f"g{i}")
            view = m.ScoreboardView([game], meta, dest_channel_id=None, owner_id=100)
            channel = _make_channel(900 + i)
            inter = _mk_click_interaction_with_guild(user_id=200 + i, channel=channel, guild_id=1)
            inter.data = {"values": [f"g{i}"]}
            views_and_inters.append((view, inter))

        tasks_created = []
        def fake_create_task(coro):
            coro.close()
            t = MagicMock()
            tasks_created.append(t)
            return t

        with patch.object(m, "get_game_summary", slow_summary), \
             patch.object(m.asyncio, "create_task", fake_create_task):
            await asyncio.gather(*(v._on_live_game_select(i) for v, i in views_and_inters))

        guild_trackers = [s for s in m._LIVE_TRACKERS.values() if s.guild_id == 1]
        assert len(guild_trackers) <= cap, (
            f"Expected at most {cap} trackers, got {len(guild_trackers)}"
        )
    asyncio.run(run())


def test_concurrent_duplicate_single_trackers_deduplicated():
    """Two simultaneous clicks on the same game+channel must produce exactly one tracker."""
    async def run():
        meta = {"week": 1, "max_week": 18, "season_type": 2, "year": 2026}

        async def slow_summary(*_a, **_kw):
            await asyncio.sleep(0)
            return {}

        game = _live_game("g1")
        channel = _make_channel(555)

        def make_view_inter(uid):
            view = m.ScoreboardView([game], meta, dest_channel_id=None, owner_id=100)
            inter = _mk_click_interaction_with_guild(user_id=uid, channel=channel, guild_id=1)
            inter.data = {"values": ["g1"]}
            return view, inter

        pairs = [make_view_inter(uid) for uid in (201, 202)]

        def fake_create_task(coro):
            coro.close()
            return MagicMock()

        with patch.object(m, "get_game_summary", slow_summary), \
             patch.object(m.asyncio, "create_task", fake_create_task):
            await asyncio.gather(*(v._on_live_game_select(i) for v, i in pairs))

        game1_trackers = [s for s in m._LIVE_TRACKERS.values()
                          if s.guild_id == 1 and s.game_id == "g1" and s.channel_id == 555]
        assert len(game1_trackers) == 1, (
            f"Expected exactly 1 tracker for g1/ch555, got {len(game1_trackers)}"
        )
    asyncio.run(run())


def test_concurrent_all_games_trackers_respect_guild_cap():
    """Firing (cap+2) simultaneous Track-All clicks must leave at most cap trackers."""
    async def run():
        meta = {"week": 1, "max_week": 18, "season_type": 2, "year": 2026}
        cap = m._MAX_TRACKERS_PER_GUILD

        async def slow_scoreboard(*_a, **_kw):
            await asyncio.sleep(0)
            return ([_live_game("g1")], meta)

        def fake_create_task(coro):
            coro.close()
            return MagicMock()

        views_and_inters = []
        for i in range(cap + 2):
            view = m.ScoreboardView([_live_game("g1")], meta, dest_channel_id=None, owner_id=100)
            channel = _make_channel(800 + i)
            inter = _mk_click_interaction_with_guild(user_id=300 + i, channel=channel, guild_id=1)
            views_and_inters.append((view, inter))

        with patch.object(m, "get_scoreboard_data", slow_scoreboard), \
             patch.object(m.asyncio, "create_task", fake_create_task):
            await asyncio.gather(*(v._track_all_live_games(i) for v, i in views_and_inters))

        guild_trackers = [s for s in m._LIVE_TRACKERS.values() if s.guild_id == 1]
        assert len(guild_trackers) <= cap, (
            f"Expected at most {cap} trackers, got {len(guild_trackers)}"
        )
    asyncio.run(run())


def test_concurrent_duplicate_all_games_trackers_deduplicated():
    """Two simultaneous Track-All clicks on the same channel yield exactly one tracker."""
    async def run():
        meta = {"week": 1, "max_week": 18, "season_type": 2, "year": 2026}

        async def slow_scoreboard(*_a, **_kw):
            await asyncio.sleep(0)
            return ([_live_game("g1")], meta)

        channel = _make_channel(777)

        def make_view_inter(uid):
            view = m.ScoreboardView([_live_game("g1")], meta, dest_channel_id=None, owner_id=100)
            inter = _mk_click_interaction_with_guild(user_id=uid, channel=channel, guild_id=1)
            return view, inter

        pairs = [make_view_inter(uid) for uid in (301, 302)]

        def fake_create_task(coro):
            coro.close()
            return MagicMock()

        with patch.object(m, "get_scoreboard_data", slow_scoreboard), \
             patch.object(m.asyncio, "create_task", fake_create_task):
            await asyncio.gather(*(v._track_all_live_games(i) for v, i in pairs))

        all_trackers = [s for s in m._LIVE_TRACKERS.values()
                        if s.guild_id == 1 and s.game_id is None and s.channel_id == 777]
        assert len(all_trackers) == 1, (
            f"Expected exactly 1 all-games tracker for ch777, got {len(all_trackers)}"
        )
    asyncio.run(run())
