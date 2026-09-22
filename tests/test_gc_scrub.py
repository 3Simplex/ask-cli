"""Pure-function tests for the gc ID-hallucination scrub (no network, no fixtures)."""
import unittest
from assets.agent import scrub_hallucinated_ids, Agent

F = chr(96) * 3
I = chr(96)


class ScrubWhitelist(unittest.TestCase):
    def test_fabricated_bracketed_stripped_with_trailing_space(self):
        out = scrub_hallucinated_ids("[usr_aaaaaa] hello world", set())
        self.assertEqual(out, "hello world")

    def test_fabricated_bare_stripped(self):
        out = scrub_hallucinated_ids("see ast_1234ab for details", set())
        self.assertEqual(out, "see  for details")

    def test_live_bracketed_and_bare_kept(self):
        live = {"usr_aaaaaa", "ast_1234ab"}
        self.assertEqual(scrub_hallucinated_ids("[usr_aaaaaa] hi", live), "[usr_aaaaaa] hi")
        self.assertEqual(scrub_hallucinated_ids("ref ast_1234ab now", live), "ref ast_1234ab now")

    def test_fenced_and_inline_code_exempt(self):
        src = "[usr_aaaaaa] before\n" + F + "\n[usr_bbbbbb]\n" + F + "\nafter " + I + "usr_cccccc" + I
        out = scrub_hallucinated_ids(src, set())
        self.assertIn("[usr_bbbbbb]", out)          # inside fence: untouched
        self.assertIn(I + "usr_cccccc" + I, out)    # inline span: untouched
        self.assertNotIn("[usr_aaaaaa]", out)       # prose: scrubbed

    def test_bare_sys_never_touched(self):
        self.assertEqual(scrub_hallucinated_ids("run sys checks now", set()), "run sys checks now")

    def test_sys_bracketed_stripped_when_not_live(self):
        self.assertEqual(scrub_hallucinated_ids("[sys] identity here", set()), "identity here")

    def test_sys_bracketed_kept_when_live(self):
        self.assertEqual(scrub_hallucinated_ids("[sys] identity", {"sys"}), "[sys] identity")

    def test_idempotency(self):
        src = "[usr_aaaaaa] text ast_deadbe [msg_000000] tail"
        once = scrub_hallucinated_ids(src, {"usr_aaaaaa"})
        twice = scrub_hallucinated_ids(once, {"usr_aaaaaa"})
        self.assertEqual(once, twice)
        self.assertEqual(once, "[usr_aaaaaa] text  tail")

    def test_bare_removal_keeps_spacing_intact(self):
        out = scrub_hallucinated_ids("a ast_baadca b", set())
        self.assertEqual(out, "a  b")


class GcActiveGate(unittest.TestCase):
    """gc_active must mirror _inject_ids_inline's gate over static+dynamic states."""

    @staticmethod
    def _stub(states, dynamic, state_name):
        stub = Agent.__new__(Agent)
        stub.states = states
        stub.dynamic_states = dynamic
        stub.state_name = state_name
        return stub

    def test_static_gc_state(self):
        a = self._stub({"cleanup": {"allowed_tools": ["gc", "set_state"]}}, {}, "cleanup")
        self.assertTrue(a.gc_active())

    def test_non_gc_state(self):
        a = self._stub({"none": {"allowed_tools": ["read"]}}, {}, "none")
        self.assertFalse(a.gc_active())

    def test_unknown_state(self):
        a = self._stub({}, {}, "nowhere")
        self.assertFalse(a.gc_active())

    def test_dynamic_gc_state(self):
        a = self._stub({}, {"made": {"allowed_tools": ["gc"]}}, "made")
        self.assertTrue(a.gc_active())


if __name__ == "__main__":
    unittest.main(verbosity=2)
