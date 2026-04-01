from __future__ import annotations


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

