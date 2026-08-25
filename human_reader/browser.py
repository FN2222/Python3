from __future__ import annotations

"""Optional Playwright backend for JavaScript course platforms.

Login is never automated: the user signs in themselves. Captchas, 403/429
and permission walls still stop the run — this module does not bypass them.
"""

from .config import ReaderConfig
from .diagrams import extract_diagrams
from .guard import inspect_http_status, inspect_page
from .htmltext import html_to_visible_text
from .models import PageContent
from .navigate import find_next_url
from .paginate import paginate_text
from .textutil import normalize_visible_text


def require_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "未安装 Playwright。请在本机执行：pip install playwright && python3 -m playwright install chromium"
        ) from exc
    return sync_playwright


class BrowserCourseSession:
    """One browser tab. Pages are opened one after another in that same tab."""

    def __init__(self, config: ReaderConfig, headed: bool = True) -> None:
        self.config = config
        self.headed = headed
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self.last_url: str | None = None

    def __enter__(self) -> "BrowserCourseSession":
        sync_playwright = require_playwright()
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=not self.headed)
        kwargs = {}
        if self.config.storage_state_path:
            kwargs["storage_state"] = self.config.storage_state_path
        self._context = self._browser.new_context(
            user_agent=self.config.user_agent,
            locale="zh-CN",
            **kwargs,
        )
        self._page = self._context.new_page()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._context is not None:
            self._context.close()
        if self._browser is not None:
            self._browser.close()
        if self._pw is not None:
            self._pw.stop()

    def wait_for_manual_login(self, url: str, storage_out: str | None = None) -> None:
        assert self._page is not None
        self._page.goto(url, wait_until="domcontentloaded", timeout=self.config.request_timeout_s * 1000)
        print("请在打开的浏览器窗口里完成登录。")
        print("不要把验证码或二次验证交给脚本。登录成功后回到终端按回车继续。")
        try:
            input()
        except EOFError as exc:
            raise RuntimeError("无法等待交互式登录（没有终端输入）。请改用 --storage-state / --cookies。") from exc
        if storage_out:
            assert self._context is not None
            self._context.storage_state(path=storage_out)
        inspect_page(self._page.content(), self._page.url, html_to_visible_text(self._page.content())[1])

    def load(self, source: str, referer: str | None = None) -> PageContent:
        del referer
        assert self._page is not None
        response = self._page.goto(
            source,
            wait_until="domcontentloaded",
            timeout=self.config.request_timeout_s * 1000,
        )
        status = response.status if response is not None else 200
        final_url = self._page.url
        inspect_http_status(status, final_url)
        html = self._page.content()
        title, text = html_to_visible_text(html)
        if not text:
            text = normalize_visible_text(html)
        inspect_page(html, final_url, text)
        page_title = title or (self._page.title() or source)
        viewports = paginate_text(text, self.config.viewport_chars, self.config.scroll_overlap)
        diagrams = extract_diagrams(html, final_url, self.config.max_assets_per_page)
        next_url = find_next_url(html, final_url, final_url)
        self.last_url = final_url
        return PageContent(
            source=source,
            title=page_title,
            text=text,
            viewports=viewports,
            diagrams=diagrams,
            next_url=next_url,
            html=html,
            final_url=final_url,
            status_code=status,
        )

    def load_bytes(self, url: str, referer: str | None = None) -> tuple[bytes, str | None]:
        del referer
        assert self._context is not None
        response = self._context.request.get(url, timeout=self.config.request_timeout_s * 1000)
        inspect_http_status(response.status, url)
        content_type = response.headers.get("content-type")
        return response.body(), content_type
