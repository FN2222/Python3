from __future__ import annotations

import re
from pathlib import Path


_BAD_CHARS = re.compile(r'[\\/:*?"<>|\s]+')


def lesson_slug(index: int, title: str, limit: int = 40) -> str:
    cleaned = _BAD_CHARS.sub("-", title.strip())
    cleaned = cleaned.strip("-._") or "lesson"
    if len(cleaned) > limit:
        cleaned = cleaned[:limit].rstrip("-._")
    return f"{index:02d}-{cleaned}"


def safe_filename(name: str, fallback: str) -> str:
    cleaned = _BAD_CHARS.sub("-", name.strip())
    cleaned = cleaned.strip("-._")
    return cleaned or fallback
