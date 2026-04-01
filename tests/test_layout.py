from __future__ import annotations

import unittest

from transprot.core.layout import compute_overlay_rect


class LayoutTests(unittest.TestCase):
    def test_overlay_stays_inside_screen(self) -> None:
        rect = compute_overlay_rect((100, 100, 200, 120), (0, 0, 800, 600), (500, 300))
        self.assertGreaterEqual(rect[0], 0)
        self.assertGreaterEqual(rect[1], 0)
        self.assertLessEqual(rect[0] + rect[2], 800)
        self.assertLessEqual(rect[1] + rect[3], 600)

    def test_overlay_falls_back_when_selection_near_bottom(self) -> None:
        rect = compute_overlay_rect((100, 520, 200, 50), (0, 0, 800, 600), (300, 150))
        self.assertLess(rect[1], 520)


if __name__ == "__main__":
    unittest.main()
