from __future__ import annotations

import re
from html.parser import HTMLParser

from .textutil import normalize_visible_text

_SKIP_TAGS = frozenset(
    {"script", "style", "noscript", "template", "svg", "iframe", "canvas"}
)
_BLOCK_TAGS = frozenset(
    {
        "p",
        "div",
        "br",
        "li",
        "ul",
        "ol",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "article",
        "section",
        "header",
        "footer",
        "tr",
        "blockquote",
        "pre",
        "hr",
        "figcaption",
    }
)
_CHARSET_RE = re.compile(
    r"charset\s*=\s*['\"]?([A-Za-z0-9._-]+)", re.IGNORECASE
)


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0
        self.title_parts: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
        if tag == "img":
            ad = {k.lower(): (v or "") for k, v in attrs}
            alt = ad.get("alt") or ad.get("title") or "配图"
            self._chunks.append(f"\n[图: {alt}]\n")
        if tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag == "title":
            self._in_title = False
        if tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title_parts.append(data)
            return
        self._chunks.append(data)

    def visible_text(self) -> str:
        return normalize_visible_text("".join(self._chunks))

    def title(self) -> str:
        return normalize_visible_text("".join(self.title_parts))


def html_to_visible_text(html: str) -> tuple[str, str]:
    parser = _VisibleTextParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        # Malformed HTML still yields whatever we parsed.
        pass
    return parser.title(), parser.visible_text()


def decode_body(data: bytes, content_type: str | None = None) -> str:
    candidates: list[str] = []
    if content_type:
        match = _CHARSET_RE.search(content_type)
        if match:
            candidates.append(match.group(1).strip().lower())
    for enc in ("utf-8", "gb18030", "gbk", "big5", "latin-1"):
        if enc not in candidates:
            candidates.append(enc)
    last_error: UnicodeDecodeError | None = None
    for enc in candidates:
        try:
            return data.decode(enc)
        except LookupError:
            continue
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
    if last_error:
        return data.decode("utf-8", errors="replace")
    return data.decode("utf-8", errors="replace")
