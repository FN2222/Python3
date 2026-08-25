from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ReadEventKind(str, Enum):
    """One atomic human-like action. A full document is never a single event."""

    OPEN = "open"
    SETTLE = "settle"
    READ_VIEWPORT = "read_viewport"
    SCROLL_DOWN = "scroll_down"
    SCROLL_UP = "scroll_up"
    PAUSE = "pause"
    IDLE = "idle"
    STUDY_DIAGRAM = "study_diagram"
    SAVE_NOTES = "save_notes"
    TURN_PAGE = "turn_page"
    DONE = "done"
    STOPPED = "stopped"


class StopReason(str, Enum):
    HTTP_STATUS = "http_status"
    LOGIN_REQUIRED = "login_required"
    CAPTCHA = "captcha"
    RATE_LIMIT = "rate_limit"
    PERMISSION = "permission"
    LOOP = "loop"
    MAX_PAGES = "max_pages"
    FINISHED = "finished"
    CONCURRENT = "concurrent"


@dataclass(frozen=True)
class Viewport:
    index: int
    text: str
    char_count: int
    start_offset: int
    end_offset: int


@dataclass
class Diagram:
    index: int
    kind: str  # img | svg | mermaid | object
    alt: str
    src: str
    caption: str = ""
    inline_svg: str = ""
    is_topology: bool = False
    local_path: str = ""


@dataclass(frozen=True)
class ReadEvent:
    kind: ReadEventKind
    page_index: int
    source: str
    duration_ms: int
    viewport_index: int | None = None
    viewport_count: int = 0
    chars: int = 0
    scroll_px: int = 0
    detail: str = ""
    excerpt: str = ""
    page_title: str = ""
    diagram_index: int | None = None
    saved_path: str = ""
    stop_reason: str = ""

    def as_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "page_index": self.page_index,
            "source": self.source,
            "duration_ms": self.duration_ms,
            "viewport_index": self.viewport_index,
            "viewport_count": self.viewport_count,
            "chars": self.chars,
            "scroll_px": self.scroll_px,
            "detail": self.detail,
            "excerpt": self.excerpt,
            "page_title": self.page_title,
            "diagram_index": self.diagram_index,
            "saved_path": self.saved_path,
            "stop_reason": self.stop_reason,
        }


@dataclass
class PageContent:
    source: str
    title: str
    text: str
    viewports: list[Viewport] = field(default_factory=list)
    diagrams: list[Diagram] = field(default_factory=list)
    next_url: str | None = None
    html: str = ""
    final_url: str = ""
    status_code: int = 200


class AccessStopped(RuntimeError):
    """Raised when the site asks a human to take over. Never bypassed."""

    def __init__(self, reason: StopReason, message: str, status_code: int | None = None, url: str = "") -> None:
        super().__init__(message)
        self.reason = reason
        self.status_code = status_code
        self.url = url
        self.message = message
