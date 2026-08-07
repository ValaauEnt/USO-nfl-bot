"""
Tests for the check-in system: _build_checkin_system() and generate_checkin().

Coverage:
  • _build_checkin_system with settings  → personality/humor/roast content present
  • _build_checkin_system with no settings → fallback path produces valid prompt
  • generate_checkin (morning & night)   → returns non-empty string (mocked OpenAI)
  • generate_checkin fallback when client is None (no API key)
  • generate_checkin error path returns graceful fallback
"""
import unittest
from unittest.mock import AsyncMock, MagicMock

from ai.personalities import PERSONALITIES
from ai.brain import _build_checkin_system, AIBrain


# ===========================================================================
# Unit tests — _build_checkin_system
# ===========================================================================

class TestBuildCheckinSystem(unittest.TestCase):

    # ── With settings ────────────────────────────────────────────────────────

    def test_with_settings_returns_nonempty_string(self):
        settings = {
            "personality": "trash_talker",
            "humor_level": "chaotic",
            "roast_level": "heavy",
        }
        result = _build_checkin_system(settings)
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 50)

    def test_with_settings_contains_personality_content(self):
        """The personality block text should appear in the prompt."""
        settings = {"personality": "trash_talker"}
        result = _build_checkin_system(settings)
        self.assertIn("TRASH TALKER", result)

    def test_with_settings_humor_key_reflected(self):
        settings = {"humor_level": "chaotic"}
        result = _build_checkin_system(settings)
        self.assertIn("CHAOTIC", result)

    def test_with_settings_roast_key_reflected(self):
        settings = {"roast_level": "savage"}
        result = _build_checkin_system(settings)
        self.assertIn("SAVAGE", result)

    def test_with_settings_length_cap_appended(self):
        """The 'SHORT' length cap instruction must always be appended."""
        settings = {"personality": "commissioner"}
        result = _build_checkin_system(settings)
        self.assertIn("SHORT", result)

    def test_with_settings_date_block_present(self):
        settings = {}
        result = _build_checkin_system(settings)
        self.assertIn("AUTHORITATIVE DATE", result)

    def test_all_personalities_produce_valid_output(self):
        """Every named personality should produce a valid non-trivial prompt."""
        for key in PERSONALITIES:
            with self.subTest(personality=key):
                result = _build_checkin_system({"personality": key})
                self.assertGreater(len(result), 50)

    def test_unknown_personality_falls_back_to_locker_room(self):
        """Unknown personality key → default locker_room block used."""
        result = _build_checkin_system({"personality": "nonexistent_key"})
        self.assertIn("LOCKER ROOM", result)

    # ── Fallback (no settings / None) ─────────────────────────────────────────

    def test_no_settings_returns_nonempty_string(self):
        result = _build_checkin_system(None)
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 50)

    def test_no_settings_fallback_contains_uce(self):
        result = _build_checkin_system(None)
        self.assertIn("Uce", result)

    def test_no_settings_fallback_date_block_present(self):
        result = _build_checkin_system(None)
        self.assertIn("AUTHORITATIVE DATE", result)

    def test_no_settings_fallback_length_cap_present(self):
        result = _build_checkin_system(None)
        self.assertIn("SHORT", result)

    def test_settings_vs_no_settings_differ(self):
        """The two paths must produce distinct prompts."""
        with_settings    = _build_checkin_system({"personality": "coach"})
        without_settings = _build_checkin_system(None)
        self.assertNotEqual(with_settings, without_settings)


# ===========================================================================
# Integration-level tests — generate_checkin (mocked OpenAI)
# ===========================================================================

def _make_brain(reply_text: str) -> AIBrain:
    """Return an AIBrain whose OpenAI client is fully mocked."""

    async def _noop_executor(name, args):
        return ""

    brain = AIBrain(_noop_executor)

    mock_message         = MagicMock()
    mock_message.content = reply_text

    mock_choice         = MagicMock()
    mock_choice.message = mock_message

    mock_resp         = MagicMock()
    mock_resp.choices = [mock_choice]

    mock_create              = AsyncMock(return_value=mock_resp)
    brain.client             = MagicMock()
    brain.client.chat.completions.create = mock_create

    return brain


class TestGenerateCheckin(unittest.IsolatedAsyncioTestCase):

    async def test_morning_checkin_returns_content(self):
        brain  = _make_brain("Good morning! Who's got fantasy decisions today? 🏈")
        result = await brain.generate_checkin("morning")
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    async def test_night_checkin_returns_content(self):
        brain  = _make_brain("How'd the day treat everyone? Drop your biggest W. 🌙")
        result = await brain.generate_checkin("night")
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    async def test_morning_with_settings_calls_openai_once(self):
        brain    = _make_brain("Rise and grind.")
        settings = {"personality": "locker_room", "humor_level": "funny", "roast_level": "light"}
        await brain.generate_checkin("morning", settings=settings)
        brain.client.chat.completions.create.assert_called_once()

    async def test_night_with_settings_calls_openai_once(self):
        brain    = _make_brain("Wrap it up.")
        settings = {"personality": "trash_talker", "humor_level": "chaotic", "roast_level": "heavy"}
        await brain.generate_checkin("night", settings=settings)
        brain.client.chat.completions.create.assert_called_once()

    async def test_morning_with_server_memories(self):
        """Server memories should be accepted and forwarded without error."""
        brain    = _make_brain("Morning fam — fantasy waiver wire closes today!")
        memories = {"league_name": "The Gridiron Gang", "commissioner": "JohnDoe"}
        result   = await brain.generate_checkin("morning", server_memories=memories)
        self.assertGreater(len(result), 0)

    async def test_personality_appears_in_system_prompt(self):
        """The system prompt sent to OpenAI must reflect the configured personality."""
        brain    = _make_brain("Night night.")
        settings = {"personality": "commissioner"}
        await brain.generate_checkin("night", settings=settings)

        call_kwargs  = brain.client.chat.completions.create.call_args
        messages     = call_kwargs.kwargs.get("messages", [])
        system_block = next(
            (m["content"] for m in messages if m.get("role") == "system"), ""
        )
        self.assertIn("COMMISSIONER", system_block)

    async def test_humor_level_appears_in_system_prompt(self):
        brain    = _make_brain("Morning!")
        settings = {"humor_level": "chaotic"}
        await brain.generate_checkin("morning", settings=settings)

        messages     = brain.client.chat.completions.create.call_args.kwargs.get("messages", [])
        system_block = next(
            (m["content"] for m in messages if m.get("role") == "system"), ""
        )
        self.assertIn("CHAOTIC", system_block)

    async def test_roast_level_appears_in_system_prompt(self):
        brain    = _make_brain("Night!")
        settings = {"roast_level": "savage"}
        await brain.generate_checkin("night", settings=settings)

        messages     = brain.client.chat.completions.create.call_args.kwargs.get("messages", [])
        system_block = next(
            (m["content"] for m in messages if m.get("role") == "system"), ""
        )
        self.assertIn("SAVAGE", system_block)

    # ── No API key (client is None) ───────────────────────────────────────────

    async def test_fallback_no_client_morning(self):
        """When client is None, morning fallback string is returned."""
        async def _noop(name, args):
            return ""

        brain        = AIBrain(_noop)
        brain.client = None
        result       = await brain.generate_checkin("morning")
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    async def test_fallback_no_client_night(self):
        """When client is None, night fallback string is returned."""
        async def _noop(name, args):
            return ""

        brain        = AIBrain(_noop)
        brain.client = None
        result       = await brain.generate_checkin("night")
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    # ── Error / edge cases ────────────────────────────────────────────────────

    async def test_empty_openai_response_returns_empty_string(self):
        """Empty content from OpenAI propagates as an empty string."""
        brain  = _make_brain("")
        result = await brain.generate_checkin("morning")
        self.assertEqual(result, "")

    async def test_openai_exception_returns_fallback_morning(self):
        """If OpenAI raises, generate_checkin returns a graceful morning fallback."""
        async def _noop(name, args):
            return ""

        brain                                    = AIBrain(_noop)
        brain.client                             = MagicMock()
        brain.client.chat.completions.create     = AsyncMock(
            side_effect=Exception("network error")
        )
        result = await brain.generate_checkin("morning")
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    async def test_openai_exception_returns_fallback_night(self):
        """If OpenAI raises, generate_checkin returns a graceful night fallback."""
        async def _noop(name, args):
            return ""

        brain                                = AIBrain(_noop)
        brain.client                         = MagicMock()
        brain.client.chat.completions.create = AsyncMock(
            side_effect=Exception("timeout")
        )
        result = await brain.generate_checkin("night")
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)


if __name__ == "__main__":
    unittest.main()
