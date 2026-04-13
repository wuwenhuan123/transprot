from __future__ import annotations

import unittest

from transprot.core.auto_mode import AutoTranslateState


class AutoTranslateStateTests(unittest.TestCase):
    def test_observe_requires_stable_duration_before_triggering(self) -> None:
        state = AutoTranslateState(stable_duration_ms=800)

        self.assertFalse(state.observe("frame-a", 1000))
        self.assertFalse(state.observe("frame-a", 1500))
        self.assertTrue(state.observe("frame-a", 1800))

    def test_same_processed_fingerprint_does_not_retrigger(self) -> None:
        state = AutoTranslateState(stable_duration_ms=200)

        self.assertFalse(state.observe("frame-a", 1000))
        self.assertTrue(state.observe("frame-a", 1200))
        state.mark_attempt_finished("frame-a")

        self.assertFalse(state.observe("frame-a", 1600))

    def test_manual_clear_suppresses_current_frame(self) -> None:
        state = AutoTranslateState(stable_duration_ms=200)

        state.suppress_current_fingerprint("frame-a")
        self.assertFalse(state.observe("frame-a", 1000))
        self.assertFalse(state.observe("frame-a", 1400))

    def test_reset_can_drop_last_success_source_text(self) -> None:
        state = AutoTranslateState(stable_duration_ms=200)
        state.mark_success_source_text("same text")

        state.reset(retain_success_source_text=False)

        self.assertIsNone(state.last_success_source_text)


if __name__ == "__main__":
    unittest.main()
