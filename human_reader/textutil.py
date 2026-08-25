from __future__ import annotations

import re
import unicodedata

_CJK_RE = re.compile(
    r"[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF"
    r"\U00020000-\U0002A6DF\U0002A700-\U0002B73F"
    r"\U0002B740-\U0002B81F\U0002B820-\U0002CEAF]"
)
_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z0-9]+)?")
_WS_RE = re.compile(r"[ \t]+")
_MULTI_NL_RE = re.compile(r"\n{3,}")


def is_cjk_char(ch: str) -> bool:
    return bool(_CJK_RE.fullmatch(ch))


def normalize_visible_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WS_RE.sub(" ", text)
    text = _MULTI_NL_RE.sub("\n\n", text)
    return text.strip()


def count_cjk_chars(text: str) -> int:
    return sum(1 for ch in text if is_cjk_char(ch))


def count_words(text: str) -> int:
    return len(_WORD_RE.findall(text))


def reading_units(text: str) -> tuple[int, int]:
    """Return (cjk_chars, latin_words) used for reading-time estimates."""
    return count_cjk_chars(text), count_words(text)


def excerpt(text: str, limit: int = 80) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "…"
