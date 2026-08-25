from __future__ import annotations

import threading
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener
from urllib.robotparser import RobotFileParser

from .config import ReaderConfig
from .cookies import load_cookie_jar
from .diagrams import extract_diagrams
from .guard import inspect_http_status, inspect_page
from .htmltext import decode_body, html_to_visible_text
from .models import AccessStopped, PageContent, StopReason
from .navigate import find_next_url
from .paginate import paginate_text
from .textutil import normalize_visible_text

_FETCH_LOCK = threading.Lock()
_IN_FLIGHT = False


class FetchError(RuntimeError):
    pass


class RobotsDisallowed(FetchError):
    pass


class ConcurrentFetchBlocked(AccessStopped):
    def __init__(self, message: str = "refusing concurrent page loads") -> None:
        super().__init__(StopReason.CONCURRENT, message)


class SerialFetcher:
    """One document in flight. Cookies come from a user-created browser session."""

    def __init__(self, config: ReaderConfig, cookie_jar: CookieJar | None = None) -> None:
        self.config = config
        if cookie_jar is not None:
            self.cookie_jar = cookie_jar
        else:
            self.cookie_jar = load_cookie_jar(config.cookies_path, config.storage_state_path)
        self._opener = build_opener(HTTPCookieProcessor(self.cookie_jar))
        self.last_url: str | None = None

    def load(self, source: str, referer: str | None = None) -> PageContent:
        global _IN_FLIGHT
        acquired = _FETCH_LOCK.acquire(blocking=False)
        if not acquired:
            raise ConcurrentFetchBlocked("已有一页正在读取，拒绝并发打开另一页")
        try:
            if _IN_FLIGHT:
                raise ConcurrentFetchBlocked("已有一页正在读取，拒绝并发打开另一页")
            _IN_FLIGHT = True
            return self._load_unlocked(source, referer or self.last_url)
        finally:
            _IN_FLIGHT = False
            _FETCH_LOCK.release()

    def load_bytes(self, url: str, referer: str | None = None) -> tuple[bytes, str | None]:
        """Fetch one asset after the page has been opened. Still serial."""
        global _IN_FLIGHT
        acquired = _FETCH_LOCK.acquire(blocking=False)
        if not acquired:
            raise ConcurrentFetchBlocked("页面读取未结束，拒绝并发下载资源")
        try:
            if _IN_FLIGHT:
                raise ConcurrentFetchBlocked("页面读取未结束，拒绝并发下载资源")
            _IN_FLIGHT = True
            path = _as_local_path(url)
            if path is not None:
                return path.read_bytes(), None
            data, content_type, status, final_url = self._http_get(url, referer or self.last_url)
            inspect_http_status(status, final_url)
            return data, content_type
        finally:
            _IN_FLIGHT = False
            _FETCH_LOCK.release()

    def _load_unlocked(self, source: str, referer: str | None) -> PageContent:
        raw_html, title_hint, final_url, status = self._read_source(source, referer)
        inspect_http_status(status, final_url)
        title, text = html_to_visible_text(raw_html)
        if not text:
            text = normalize_visible_text(raw_html)
        inspect_page(raw_html, final_url, text)
        page_title = title or title_hint or source
        viewports = paginate_text(text, self.config.viewport_chars, self.config.scroll_overlap)
        diagrams = extract_diagrams(raw_html, final_url or source, self.config.max_assets_per_page)
        next_url = find_next_url(raw_html, final_url or source, final_url or source)
        self.last_url = final_url or source
        return PageContent(
            source=source,
            title=page_title,
            text=text,
            viewports=viewports,
            diagrams=diagrams,
            next_url=next_url,
            html=raw_html,
            final_url=final_url or source,
            status_code=status,
        )

    def _read_source(self, source: str, referer: str | None) -> tuple[str, str, str, int]:
        path = _as_local_path(source)
        if path is not None:
            data = path.read_bytes()
            html = decode_body(data, None)
            final = path.resolve().as_uri()
            return html, path.stem, final, 200

        parsed = urlparse(source)
        if parsed.scheme not in {"http", "https"}:
            raise FetchError(f"unsupported source: {source!r}")
        if self.config.check_robots and not _robots_allows(source, self.config):
            raise RobotsDisallowed(f"robots.txt disallows {source}")

        data, content_type, status, final_url = self._http_get(source, referer)
        title_hint = urlparse(final_url).path.rsplit("/", 1)[-1]
        return decode_body(data, content_type), title_hint, final_url, status

    def _http_get(self, url: str, referer: str | None) -> tuple[bytes, str | None, int, str]:
        headers = {
            "User-Agent": self.config.user_agent,
            "Accept": (
                "text/html,application/xhtml+xml,image/avif,image/webp,"
                "image/svg+xml;q=0.9,*/*;q=0.8"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        if referer:
            headers["Referer"] = referer
        request = Request(url, headers=headers, method="GET")
        try:
            response = self._opener.open(request, timeout=self.config.request_timeout_s)
            try:
                status = getattr(response, "status", None) or response.getcode() or 200
                content_type = response.headers.get("Content-Type")
                data = response.read()
                final_url = response.geturl() or url
            finally:
                response.close()
        except HTTPError as exc:
            inspect_http_status(exc.code, url)
            raise FetchError(f"HTTP {exc.code} for {url}") from exc
        except URLError as exc:
            raise FetchError(f"failed to fetch {url}: {exc.reason}") from exc
        inspect_http_status(int(status), final_url)
        return data, content_type, int(status), final_url


def load_page(source: str, config: ReaderConfig) -> PageContent:
    return SerialFetcher(config).load(source)


def _as_local_path(source: str) -> Path | None:
    if source.startswith("file:"):
        parsed = urlparse(source)
        return Path(parsed.path)
    path = Path(source)
    if path.exists() and path.is_file():
        return path
    return None


def _robots_allows(url: str, config: ReaderConfig) -> bool:
    parsed = urlparse(url)
    robots_url = urljoin(f"{parsed.scheme}://{parsed.netloc}", "/robots.txt")
    parser = RobotFileParser()
    parser.set_url(robots_url)
    try:
        parser.read()
    except Exception:
        return True
    try:
        return parser.can_fetch(config.user_agent, url)
    except Exception:
        return True
