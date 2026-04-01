from __future__ import annotations

from collections.abc import Sequence

from transprot.core.models import CaptureRegion

ScreenRect = tuple[int, int, int, int]
DEFAULT_CAPTURE_SIZE = (480, 240)
MIN_CAPTURE_SIZE = (240, 120)


def compute_overlay_rect(
    selection_rect: tuple[int, int, int, int],
    screen_rect: tuple[int, int, int, int],
    preferred_size: tuple[int, int],
    margin: int = 12,
) -> tuple[int, int, int, int]:
    sx, sy, sw, sh = screen_rect
    x, y, w, h = selection_rect
    pref_w = min(preferred_size[0], sw - (margin * 2))
    pref_h = min(preferred_size[1], sh - (margin * 2))

    candidates = [
        (x, y, pref_w, pref_h),
        (x, y + h + margin, pref_w, pref_h),
        (x, y - pref_h - margin, pref_w, pref_h),
        (sx + margin, sy + margin, pref_w, pref_h),
    ]

    for cx, cy, cw, ch in candidates:
        if cx >= sx + margin and cy >= sy + margin and cx + cw <= sx + sw - margin and cy + ch <= sy + sh - margin:
            return cx, cy, cw, ch

    clamped_x = min(max(x, sx + margin), sx + sw - pref_w - margin)
    clamped_y = min(max(y, sy + margin), sy + sh - pref_h - margin)
    return clamped_x, clamped_y, pref_w, pref_h


def build_default_capture_region(
    screen_name: str,
    screen_rect: ScreenRect,
    default_size: tuple[int, int] = DEFAULT_CAPTURE_SIZE,
) -> CaptureRegion:
    sx, sy, sw, sh = screen_rect
    width = min(default_size[0], sw)
    height = min(default_size[1], sh)
    x = sx + max((sw - width) // 2, 0)
    y = sy + max((sh - height) // 2, 0)
    return CaptureRegion(screen_name=screen_name, x=x, y=y, width=width, height=height)


def clamp_capture_region(
    region: CaptureRegion,
    screen_rect: ScreenRect,
    min_size: tuple[int, int] = MIN_CAPTURE_SIZE,
) -> CaptureRegion:
    sx, sy, sw, sh = screen_rect
    min_width = min(min_size[0], sw)
    min_height = min(min_size[1], sh)
    width = min(max(region.width, min_width), sw)
    height = min(max(region.height, min_height), sh)
    x = min(max(region.x, sx), sx + sw - width)
    y = min(max(region.y, sy), sy + sh - height)
    return CaptureRegion(
        screen_name=region.screen_name,
        x=x,
        y=y,
        width=width,
        height=height,
    )


def resolve_capture_region(
    saved_region: CaptureRegion | None,
    screens: Sequence[tuple[str, ScreenRect]],
    primary_screen_name: str,
) -> CaptureRegion:
    if not screens:
        raise ValueError("At least one screen is required.")

    screen_map = dict(screens)
    fallback_name = primary_screen_name if primary_screen_name in screen_map else screens[0][0]
    if saved_region is not None and saved_region.screen_name in screen_map:
        return clamp_capture_region(saved_region, screen_map[saved_region.screen_name])
    return build_default_capture_region(fallback_name, screen_map[fallback_name])
