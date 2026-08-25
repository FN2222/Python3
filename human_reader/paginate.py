from __future__ import annotations

from .models import Viewport


def paginate_text(
    text: str,
    viewport_chars: int,
    overlap_ratio: float,
) -> list[Viewport]:
    """Split a document into overlapping screens. Never one giant viewport.

    A human only sees one screen at a time. Overlap mimics incomplete
    scrolls (the bottom of the previous screen stays in view).
    """
    if viewport_chars < 80:
        raise ValueError("viewport_chars must be at least 80")
    if not 0 <= overlap_ratio < 0.8:
        raise ValueError("scroll_overlap must be in [0, 0.8)")

    stripped = text.strip()
    if not stripped:
        return [
            Viewport(
                index=0,
                text="",
                char_count=0,
                start_offset=0,
                end_offset=0,
            )
        ]

    step = max(1, int(viewport_chars * (1.0 - overlap_ratio)))
    viewports: list[Viewport] = []
    start = 0
    length = len(stripped)
    index = 0
    while start < length:
        end = min(length, start + viewport_chars)
        # Prefer breaking at a paragraph or sentence near the end of the screen.
        if end < length:
            window = stripped[start:end]
            break_at = _prefer_break(window)
            if break_at >= viewport_chars // 3:
                end = start + break_at
        chunk = stripped[start:end].strip()
        if chunk or not viewports:
            viewports.append(
                Viewport(
                    index=index,
                    text=chunk,
                    char_count=len(chunk),
                    start_offset=start,
                    end_offset=end,
                )
            )
            index += 1
        if end >= length:
            break
        next_start = start + step
        if next_start <= start:
            next_start = start + 1
        # Do not skip past end; keep moving forward.
        if next_start >= end:
            start = end
        else:
            start = next_start
        if len(viewports) > 10_000:
            raise RuntimeError("pagination produced too many viewports")
    return viewports


def _prefer_break(window: str) -> int:
    for sep in ("\n\n", "。", "！", "？", ".\n", "!\n", "?\n", "\n", "；", ";", "，", ","):
        pos = window.rfind(sep)
        if pos >= len(window) // 3:
            return pos + len(sep)
    # Fall back to last whitespace.
    pos = window.rfind(" ")
    if pos >= len(window) // 3:
        return pos + 1
    return len(window)
