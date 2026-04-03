from __future__ import annotations

import unittest

from transprot.core.layout import (
    build_default_capture_region,
    clamp_capture_region,
    compute_overlay_rect,
    resolve_capture_region,
)
from transprot.core.models import CaptureRegion


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

    def test_default_capture_region_is_centered(self) -> None:
        region = build_default_capture_region("Primary", (0, 0, 1200, 800))
        self.assertEqual(region.width, 480)
        self.assertEqual(region.height, 240)
        self.assertEqual(region.x, 360)
        self.assertEqual(region.y, 280)

    def test_clamp_capture_region_keeps_region_inside_screen(self) -> None:
        region = clamp_capture_region(
            CaptureRegion(screen_name="Primary", x=-100, y=700, width=700, height=300),
            (0, 0, 800, 600),
        )
        self.assertEqual(region.x, 0)
        self.assertEqual(region.y, 300)
        self.assertEqual(region.width, 700)
        self.assertEqual(region.height, 300)

    def test_resolve_capture_region_falls_back_when_screen_missing(self) -> None:
        region = resolve_capture_region(
            CaptureRegion(screen_name="Missing", x=20, y=20, width=400, height=200),
            [("Primary", (0, 0, 1200, 800))],
            "Primary",
        )
        self.assertEqual(region.screen_name, "Primary")
        self.assertEqual(region.width, 480)
        self.assertEqual(region.height, 240)

    def test_clamp_capture_region_allows_very_small_region(self) -> None:
        region = clamp_capture_region(
            CaptureRegion(screen_name="Primary", x=10, y=12, width=6, height=5),
            (0, 0, 800, 600),
        )
        self.assertEqual(region.x, 10)
        self.assertEqual(region.y, 12)
        self.assertEqual(region.width, 6)
        self.assertEqual(region.height, 5)


if __name__ == "__main__":
    unittest.main()
