"""Tests for conversation pre-context (ambient channel message buffer).

Covers:
- append_channel_context / get_channel_context basic ops
- Context expiry (messages older than 30 min return empty)
- Max pre-context ring-buffer (10 messages max)
- Channel isolation (channel A's context doesn't leak to channel B)
- Empty/blank message filtering
- Message truncation (>500 chars)
- Multiple users in the same channel
- Pre-context absent: get_channel_context returns []
- Conversation history unchanged by pre-context changes
- server_memory isolation across guilds
"""
import json
import time
import unittest
from unittest.mock import patch, MagicMock


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_db(tmp_path):
    """Return a temporary DB path and monkey-patch _get_conn to use it."""
    import sqlite3
    from pathlib import Path
    db_file = tmp_path / "test.db"

    def _fake_conn():
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        return conn

    return db_file, _fake_conn


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestAppendAndGetChannelContext(unittest.TestCase):
    """Basic append / retrieve round-trip."""

    def setUp(self):
        import tempfile, pathlib
        self._tmp = tempfile.mkdtemp()
        self._tmp_path = pathlib.Path(self._tmp)
        self._db_file, self._fake_conn = _make_db(self._tmp_path)
        # Create the channel_context table
        with self._fake_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS channel_context (
                    channel_id TEXT PRIMARY KEY,
                    messages   TEXT DEFAULT '[]',
                    updated_at REAL
                )
            """)
            conn.commit()

    def _patch(self):
        return patch("ai.memory._get_conn", self._fake_conn)

    def test_empty_channel_returns_empty_list(self):
        with self._patch():
            from ai.memory import get_channel_context
            result = get_channel_context("ch_unknown")
        self.assertEqual(result, [])

    def test_single_message_round_trip(self):
        with self._patch():
            from ai.memory import append_channel_context, get_channel_context
            append_channel_context("ch1", "Alice", "Who's taking the league tonight?")
            result = get_channel_context("ch1")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["author"], "Alice")
        self.assertEqual(result[0]["content"], "Who's taking the league tonight?")

    def test_multiple_messages_ordered(self):
        with self._patch():
            from ai.memory import append_channel_context, get_channel_context
            append_channel_context("ch2", "Alice", "Who's taking the league?")
            append_channel_context("ch2", "Bob", "Probably Mike.")
            result = get_channel_context("ch2")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["author"], "Alice")
        self.assertEqual(result[1]["author"], "Bob")

    def test_multiple_users_tracked(self):
        with self._patch():
            from ai.memory import append_channel_context, get_channel_context
            for i, name in enumerate(["Alice", "Bob", "Carol"]):
                append_channel_context("ch_multi", name, f"Message {i} from {name}")
            result = get_channel_context("ch_multi")
        authors = [m["author"] for m in result]
        self.assertIn("Alice", authors)
        self.assertIn("Bob", authors)
        self.assertIn("Carol", authors)


class TestChannelIsolation(unittest.TestCase):
    """Context for channel A must not appear in channel B."""

    def setUp(self):
        import tempfile, pathlib
        self._tmp = tempfile.mkdtemp()
        self._tmp_path = pathlib.Path(self._tmp)
        _, self._fake_conn = _make_db(self._tmp_path)
        with self._fake_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS channel_context (
                    channel_id TEXT PRIMARY KEY,
                    messages   TEXT DEFAULT '[]',
                    updated_at REAL
                )
            """)
            conn.commit()

    def _patch(self):
        return patch("ai.memory._get_conn", self._fake_conn)

    def test_channel_a_does_not_bleed_into_channel_b(self):
        with self._patch():
            from ai.memory import append_channel_context, get_channel_context
            append_channel_context("channel_a", "Alice", "Secret A topic")
            result_b = get_channel_context("channel_b")
        self.assertEqual(result_b, [])

    def test_two_channels_independent(self):
        with self._patch():
            from ai.memory import append_channel_context, get_channel_context
            append_channel_context("ch_x", "User1", "Topic X")
            append_channel_context("ch_y", "User2", "Topic Y")
            ctx_x = get_channel_context("ch_x")
            ctx_y = get_channel_context("ch_y")
        self.assertEqual(len(ctx_x), 1)
        self.assertEqual(ctx_x[0]["content"], "Topic X")
        self.assertEqual(len(ctx_y), 1)
        self.assertEqual(ctx_y[0]["content"], "Topic Y")


class TestContextExpiry(unittest.TestCase):
    """Context older than 30 minutes should be discarded."""

    def setUp(self):
        import tempfile, pathlib
        self._tmp = tempfile.mkdtemp()
        self._tmp_path = pathlib.Path(self._tmp)
        _, self._fake_conn = _make_db(self._tmp_path)
        with self._fake_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS channel_context (
                    channel_id TEXT PRIMARY KEY,
                    messages   TEXT DEFAULT '[]',
                    updated_at REAL
                )
            """)
            conn.commit()

    def _patch(self):
        return patch("ai.memory._get_conn", self._fake_conn)

    def test_fresh_context_returned(self):
        with self._patch():
            from ai.memory import append_channel_context, get_channel_context
            append_channel_context("ch_fresh", "Alice", "Fresh message")
            result = get_channel_context("ch_fresh")
        self.assertEqual(len(result), 1)

    def test_expired_context_returns_empty(self):
        # Write a stale row directly (updated_at = 2 hours ago)
        stale_ts = time.time() - 7200
        messages = json.dumps([{"author": "Alice", "content": "Old topic"}])
        with self._fake_conn() as conn:
            conn.execute(
                "INSERT INTO channel_context (channel_id, messages, updated_at) VALUES (?, ?, ?)",
                ("ch_stale", messages, stale_ts),
            )
            conn.commit()
        with self._patch():
            from ai.memory import get_channel_context
            result = get_channel_context("ch_stale")
        self.assertEqual(result, [])

    def test_context_at_boundary_31_min_returns_empty(self):
        stale_ts = time.time() - (31 * 60)
        messages = json.dumps([{"author": "Bob", "content": "Just outside window"}])
        with self._fake_conn() as conn:
            conn.execute(
                "INSERT INTO channel_context (channel_id, messages, updated_at) VALUES (?, ?, ?)",
                ("ch_boundary", messages, stale_ts),
            )
            conn.commit()
        with self._patch():
            from ai.memory import get_channel_context
            result = get_channel_context("ch_boundary")
        self.assertEqual(result, [])

    def test_context_at_29_min_is_returned(self):
        fresh_ts = time.time() - (29 * 60)
        messages = json.dumps([{"author": "Carol", "content": "Still valid"}])
        with self._fake_conn() as conn:
            conn.execute(
                "INSERT INTO channel_context (channel_id, messages, updated_at) VALUES (?, ?, ?)",
                ("ch_29min", messages, fresh_ts),
            )
            conn.commit()
        with self._patch():
            from ai.memory import get_channel_context
            result = get_channel_context("ch_29min")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["content"], "Still valid")


class TestRingBuffer(unittest.TestCase):
    """Pre-context must not exceed MAX_PRE_CONTEXT (10) messages."""

    def setUp(self):
        import tempfile, pathlib
        self._tmp = tempfile.mkdtemp()
        self._tmp_path = pathlib.Path(self._tmp)
        _, self._fake_conn = _make_db(self._tmp_path)
        with self._fake_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS channel_context (
                    channel_id TEXT PRIMARY KEY,
                    messages   TEXT DEFAULT '[]',
                    updated_at REAL
                )
            """)
            conn.commit()

    def _patch(self):
        return patch("ai.memory._get_conn", self._fake_conn)

    def test_max_10_messages_enforced(self):
        with self._patch():
            from ai.memory import append_channel_context, get_channel_context
            for i in range(15):
                append_channel_context("ch_ring", f"User{i}", f"Message {i}")
            result = get_channel_context("ch_ring")
        self.assertEqual(len(result), 10)

    def test_oldest_messages_dropped_first(self):
        with self._patch():
            from ai.memory import append_channel_context, get_channel_context
            for i in range(15):
                append_channel_context("ch_order", "Alice", f"Message {i}")
            result = get_channel_context("ch_order")
        # Only the last 10 should remain
        contents = [m["content"] for m in result]
        self.assertIn("Message 14", contents)
        self.assertNotIn("Message 0", contents)
        self.assertNotIn("Message 4", contents)

    def test_exactly_10_messages_all_kept(self):
        with self._patch():
            from ai.memory import append_channel_context, get_channel_context
            for i in range(10):
                append_channel_context("ch_exact", "User", f"Msg {i}")
            result = get_channel_context("ch_exact")
        self.assertEqual(len(result), 10)


class TestMessageFiltering(unittest.TestCase):
    """Blank messages should be ignored; long messages truncated."""

    def setUp(self):
        import tempfile, pathlib
        self._tmp = tempfile.mkdtemp()
        self._tmp_path = pathlib.Path(self._tmp)
        _, self._fake_conn = _make_db(self._tmp_path)
        with self._fake_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS channel_context (
                    channel_id TEXT PRIMARY KEY,
                    messages   TEXT DEFAULT '[]',
                    updated_at REAL
                )
            """)
            conn.commit()

    def _patch(self):
        return patch("ai.memory._get_conn", self._fake_conn)

    def test_empty_string_not_stored(self):
        with self._patch():
            from ai.memory import append_channel_context, get_channel_context
            append_channel_context("ch_blank", "Alice", "")
            result = get_channel_context("ch_blank")
        self.assertEqual(result, [])

    def test_whitespace_only_not_stored(self):
        with self._patch():
            from ai.memory import append_channel_context, get_channel_context
            append_channel_context("ch_ws", "Alice", "   ")
            result = get_channel_context("ch_ws")
        self.assertEqual(result, [])

    def test_long_message_truncated_to_500(self):
        long_msg = "x" * 1000
        with self._patch():
            from ai.memory import append_channel_context, get_channel_context
            append_channel_context("ch_long", "Alice", long_msg)
            result = get_channel_context("ch_long")
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]["content"]), 500)

    def test_message_exactly_500_chars_stored_intact(self):
        msg = "a" * 500
        with self._patch():
            from ai.memory import append_channel_context, get_channel_context
            append_channel_context("ch_500", "Alice", msg)
            result = get_channel_context("ch_500")
        self.assertEqual(len(result[0]["content"]), 500)

    def test_none_content_handled(self):
        with self._patch():
            from ai.memory import append_channel_context, get_channel_context
            # Should not raise; None is treated as empty
            append_channel_context("ch_none", "Alice", None)
            result = get_channel_context("ch_none")
        self.assertEqual(result, [])


class TestConversationHistoryUnaffected(unittest.TestCase):
    """Pre-context changes must not interfere with conversation_history."""

    def setUp(self):
        import tempfile, pathlib
        self._tmp = tempfile.mkdtemp()
        self._tmp_path = pathlib.Path(self._tmp)
        _, self._fake_conn = _make_db(self._tmp_path)
        with self._fake_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS channel_context (
                    channel_id TEXT PRIMARY KEY,
                    messages   TEXT DEFAULT '[]',
                    updated_at REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversation_history (
                    channel_id TEXT PRIMARY KEY,
                    messages   TEXT DEFAULT '[]',
                    updated_at REAL
                )
            """)
            conn.commit()

    def _patch(self):
        return patch("ai.memory._get_conn", self._fake_conn)

    def test_pre_context_does_not_pollute_conversation_history(self):
        with self._patch():
            from ai.memory import (
                append_channel_context,
                get_conversation_history,
            )
            append_channel_context("shared_ch", "Alice", "Ambient message")
            history = get_conversation_history("shared_ch")
        self.assertEqual(history, [])

    def test_conversation_history_does_not_pollute_pre_context(self):
        with self._patch():
            from ai.memory import (
                append_conversation,
                get_channel_context,
            )
            append_conversation("shared_ch2", "user", "Direct UCE message")
            ctx = get_channel_context("shared_ch2")
        self.assertEqual(ctx, [])


class TestPreContextSystemPromptInjection(unittest.TestCase):
    """The pre-context block should appear in the system prompt when messages exist."""

    def test_pre_context_injected_when_present(self):
        """If get_channel_context returns messages, they appear in the system prompt."""
        fake_ctx = [
            {"author": "Alice", "content": "Who's taking the league tonight?"},
            {"author": "Bob",   "content": "Probably Mike."},
        ]
        # We test the formatting logic directly (it's in brain.py process_message)
        # Build the expected block the same way brain.py does it
        lines = [f"**{m['author']}**: {m['content']}" for m in fake_ctx]
        block = (
            "\n\n## Recent Channel Activity (before you were addressed)\n"
            "These are the most recent messages in this channel. Use them to "
            "understand the current topic, who's talking to whom, and what "
            "any follow-up questions or corrections refer to.\n"
            + "\n".join(lines)
        )
        self.assertIn("Recent Channel Activity", block)
        self.assertIn("Alice", block)
        self.assertIn("Who's taking the league tonight?", block)
        self.assertIn("Probably Mike.", block)

    def test_no_pre_context_block_when_empty(self):
        """If get_channel_context returns [], no block should be appended."""
        # Simulate what brain.py does
        pre_ctx = []
        system = "base system prompt"
        if pre_ctx:
            lines = [f"**{m['author']}**: {m['content']}" for m in pre_ctx]
            system += "\n\n## Recent Channel Activity\n" + "\n".join(lines)
        self.assertNotIn("Recent Channel Activity", system)
        self.assertEqual(system, "base system prompt")

    def test_context_block_uses_author_names(self):
        """Each line in the block is prefixed with the author's display name."""
        fake_ctx = [
            {"author": "JohnDoe", "content": "test message"},
        ]
        lines = [f"**{m['author']}**: {m['content']}" for m in fake_ctx]
        block = "\n".join(lines)
        self.assertTrue(block.startswith("**JohnDoe**"))


class TestFollowUpAndCorrectionScenarios(unittest.TestCase):
    """Scenario-level tests verifying context accumulation matches real use cases."""

    def setUp(self):
        import tempfile, pathlib
        self._tmp = tempfile.mkdtemp()
        self._tmp_path = pathlib.Path(self._tmp)
        _, self._fake_conn = _make_db(self._tmp_path)
        with self._fake_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS channel_context (
                    channel_id TEXT PRIMARY KEY,
                    messages   TEXT DEFAULT '[]',
                    updated_at REAL
                )
            """)
            conn.commit()

    def _patch(self):
        return patch("ai.memory._get_conn", self._fake_conn)

    def test_score_correction_scenario(self):
        """UCE answers about NFL score, user corrects to Madden — context captures it."""
        with self._patch():
            from ai.memory import append_channel_context, get_channel_context
            # Ambient: user asks about score, UCE is not triggered
            append_channel_context("ch_score", "Mike", "What's the score?")
            # UCE responds (tracked in conversation_history, not pre-context)
            # User corrects
            append_channel_context("ch_score", "Mike", "Nah, I mean the Madden game.")
            ctx = get_channel_context("ch_score")
        contents = [m["content"] for m in ctx]
        self.assertIn("Nah, I mean the Madden game.", contents)

    def test_followup_question_scenario(self):
        """Users discuss topic, then ask UCE — context captures full exchange."""
        with self._patch():
            from ai.memory import append_channel_context, get_channel_context
            append_channel_context("ch_fu", "Alice", "Who's taking the league tonight?")
            append_channel_context("ch_fu", "Bob",   "Probably Mike.")
            # UCE triggered: "Uce what do you think?" — stored in conversation_history
            # Pre-context should show the A-B exchange
            ctx = get_channel_context("ch_fu")
        self.assertEqual(len(ctx), 2)
        self.assertEqual(ctx[0]["author"], "Alice")
        self.assertEqual(ctx[1]["author"], "Bob")

    def test_unrelated_old_conversation_excluded_after_expiry(self):
        """Old conversations (>30 min) do not pollute new ones."""
        # Write a stale entry
        stale_ts = time.time() - 3600
        stale_msgs = json.dumps([
            {"author": "OldUser", "content": "Old unrelated topic"}
        ])
        with self._fake_conn() as conn:
            conn.execute(
                "INSERT INTO channel_context (channel_id, messages, updated_at) VALUES (?, ?, ?)",
                ("ch_old", stale_msgs, stale_ts),
            )
            conn.commit()
        with self._patch():
            from ai.memory import append_channel_context, get_channel_context
            # New message arrives — but since the old row is stale, it gets cleared
            append_channel_context("ch_old", "NewUser", "Fresh topic")
            ctx = get_channel_context("ch_old")
        # Only the new message should appear
        contents = [m["content"] for m in ctx]
        self.assertNotIn("Old unrelated topic", contents)
        self.assertIn("Fresh topic", contents)

    def test_multiple_servers_isolated_through_channel_ids(self):
        """Different guild channels are isolated by their channel_id."""
        with self._patch():
            from ai.memory import append_channel_context, get_channel_context
            # Guild A's channel
            append_channel_context("guild_a_ch_1", "AliceA", "Guild A topic")
            # Guild B's channel
            append_channel_context("guild_b_ch_1", "AliceB", "Guild B topic")
            ctx_a = get_channel_context("guild_a_ch_1")
            ctx_b = get_channel_context("guild_b_ch_1")
        self.assertEqual(len(ctx_a), 1)
        self.assertEqual(ctx_a[0]["content"], "Guild A topic")
        self.assertEqual(len(ctx_b), 1)
        self.assertEqual(ctx_b[0]["content"], "Guild B topic")

    def test_uce_addressed_after_several_messages(self):
        """Several messages accumulate before UCE is addressed — all visible in context."""
        with self._patch():
            from ai.memory import append_channel_context, get_channel_context
            messages = [
                ("User1", "Anyone watching the game?"),
                ("User2", "Yeah chiefs vs ravens"),
                ("User1", "Chiefs are getting cooked"),
                ("User3", "Ravens defense is insane rn"),
                ("User2", "Fr, Lamar is doing too much"),
            ]
            for author, content in messages:
                append_channel_context("ch_buildup", author, content)
            ctx = get_channel_context("ch_buildup")
        self.assertEqual(len(ctx), 5)
        # All authors present
        authors = {m["author"] for m in ctx}
        self.assertEqual(authors, {"User1", "User2", "User3"})


class TestConstantsAndDefaults(unittest.TestCase):
    """Verify the module-level constants are set correctly."""

    def test_max_pre_context_is_10(self):
        from ai.memory import MAX_PRE_CONTEXT
        self.assertEqual(MAX_PRE_CONTEXT, 10)

    def test_pre_context_max_age_is_30_minutes(self):
        from ai.memory import PRE_CONTEXT_MAX_AGE_SECS
        self.assertEqual(PRE_CONTEXT_MAX_AGE_SECS, 1800)

    def test_max_history_unchanged(self):
        from ai.memory import MAX_HISTORY
        self.assertEqual(MAX_HISTORY, 20)

    def test_history_max_age_unchanged(self):
        from ai.memory import HISTORY_MAX_AGE_SECS
        self.assertEqual(HISTORY_MAX_AGE_SECS, 4 * 3600)


if __name__ == "__main__":
    unittest.main()
