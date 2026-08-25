from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlparse

# Visible labels a student would click to go to the next lesson/page.
_NEXT_LABELS = (
    "下一页",
    "下一课",
    "下一章",
    "下一节",
    "下一项",
    "后一页",
    "后一课",
    "继续学习",
    "下一篇",
    "next lesson",
    "next page",
    "next chapter",
    "next",
    "continue",
)

_SKIP_HREF_RE = re.compile(
    r"^(javascript:|mailto:|tel:|#)$",
    re.IGNORECASE,
)
_LOGIN_HREF_RE = re.compile(
    r"/(login|signin|sign-in|passport|sso)(/|$|\?)",
    re.IGNORECASE,
)


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[dict] = []
        self._current: dict | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        ad = {k.lower(): (v or "") for k, v in attrs}
        self._current = {
            "href": ad.get("href", ""),
            "rel": ad.get("rel", ""),
            "aria": ad.get("aria-label", ""),
            "cls": ad.get("class", ""),
            "id": ad.get("id", ""),
            "text": "",
        }

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self._current["text"] += data

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._current is not None:
            self.links.append(self._current)
            self._current = None


def find_next_url(html: str, base_url: str, current_url: str) -> str | None:
    """Pick the next lesson from THIS page only.

    Does not crawl a table of contents into a URL list, and does not
    prefetch later chapters.
    """
    parser = _LinkParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        pass

    current_norm = _normalize_url(current_url)
    rel_next = None
    labeled = None
    outline_next = _outline_next(parser.links, base_url, current_norm)

    for link in parser.links:
        href = (link.get("href") or "").strip()
        if not href or _SKIP_HREF_RE.match(href):
            continue
        abs_url = _absolute(base_url, href)
        if not abs_url or _normalize_url(abs_url) == current_norm:
            continue
        if _LOGIN_HREF_RE.search(urlparse(abs_url).path):
            continue
        rel = (link.get("rel") or "").lower()
        if "next" in rel.split():
            rel_next = abs_url
            break
        blob = " ".join(
            [
                link.get("text") or "",
                link.get("aria") or "",
                link.get("cls") or "",
                link.get("id") or "",
            ]
        ).lower()
        if labeled is None and _is_next_label(blob):
            labeled = abs_url

    return rel_next or labeled or outline_next


def _is_next_label(blob: str) -> bool:
    compact = re.sub(r"\s+", " ", blob).strip().lower()
    for label in _NEXT_LABELS:
        if label in compact:
            # Avoid "next" matching "next.js" asset links, etc.
            if label == "next" and "lesson" not in compact and "page" not in compact and "章" not in compact and "课" not in compact:
                if compact.strip() in {"next", "next >", "next »", "> next"}:
                    return True
                if re.search(r"\bnext\b", compact) and len(compact) < 24:
                    return True
                continue
            return True
    return False


def _outline_next(links: list[dict], base_url: str, current_norm: str) -> str | None:
    """If the sidebar already lists lessons, take only the item after the current one."""
    resolved: list[str] = []
    for link in links:
        href = (link.get("href") or "").strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            continue
        abs_url = _absolute(base_url, href)
        if not abs_url:
            continue
        norm = _normalize_url(abs_url)
        if not resolved or resolved[-1] != norm:
            resolved.append(norm)
    try:
        idx = resolved.index(current_norm)
    except ValueError:
        return None
    if idx + 1 < len(resolved):
        candidate = resolved[idx + 1]
        if _LOGIN_HREF_RE.search(urlparse(candidate).path):
            return None
        return candidate
    return None


def _absolute(base_url: str, href: str) -> str | None:
    try:
        joined = urljoin(base_url, href)
    except ValueError:
        return None
    joined, _frag = urldefrag(joined)
    parsed = urlparse(joined)
    if parsed.scheme in {"http", "https"}:
        return joined
    if parsed.scheme in {"", "file"}:
        return joined
    return None


def _normalize_url(url: str) -> str:
    url, _frag = urldefrag(url)
    parsed = urlparse(url)
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    if parsed.scheme in {"http", "https"}:
        netloc = parsed.netloc.lower()
        return f"{parsed.scheme}://{netloc}{path}" + (f"?{parsed.query}" if parsed.query else "")
    if parsed.scheme == "file":
        return f"file://{path}"
    return path
