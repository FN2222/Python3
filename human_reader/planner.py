from __future__ import annotations

import random

from .config import ReaderConfig
from .models import PageContent, ReadEvent, ReadEventKind
from .timing import reading_time_ms, uniform_ms


def plan_page(
    page: PageContent,
    config: ReaderConfig,
    rng: random.Random,
    page_index: int,
) -> list[ReadEvent]:
    """Serial student actions for one lesson page.

    Order: open → settle → read each screen (scroll between them) →
    study diagrams → organise notes. Never a single bulk-read action.
    """
    viewports = page.viewports
    if not viewports:
        raise ValueError("page has no viewports")

    events: list[ReadEvent] = []
    n = len(viewports)

    events.append(
        _event(
            ReadEventKind.OPEN,
            page,
            page_index,
            duration_ms=uniform_ms(rng, 180, 480),
            viewport_count=n,
            detail="打开这一课，只看到首屏",
        )
    )
    events.append(
        _event(
            ReadEventKind.SETTLE,
            page,
            page_index,
            duration_ms=uniform_ms(rng, config.settle_ms_min, config.settle_ms_max),
            viewport_count=n,
            detail="等页面稳定，目光停在顶部",
        )
    )

    i = 0
    while i < n:
        vp = viewports[i]
        read_ms = reading_time_ms(vp.text, config, rng, i)
        events.append(
            _event(
                ReadEventKind.READ_VIEWPORT,
                page,
                page_index,
                duration_ms=read_ms,
                viewport_index=i,
                viewport_count=n,
                chars=vp.char_count,
                excerpt=vp.text,
                detail=f"阅读第 {i + 1}/{n} 屏",
            )
        )

        if i < n - 1 and rng.random() < config.pause_probability:
            events.append(
                _event(
                    ReadEventKind.PAUSE,
                    page,
                    page_index,
                    duration_ms=uniform_ms(rng, config.pause_ms_min, config.pause_ms_max),
                    viewport_index=i,
                    viewport_count=n,
                    detail="停下来想一下",
                )
            )

        if i < n - 1 and rng.random() < config.idle_probability:
            events.append(
                _event(
                    ReadEventKind.IDLE,
                    page,
                    page_index,
                    duration_ms=uniform_ms(rng, config.idle_ms_min, config.idle_ms_max),
                    viewport_index=i,
                    viewport_count=n,
                    detail="短暂离开（走神 / 看别的）",
                )
            )

        if i > 0 and i < n - 1 and rng.random() < config.reread_probability:
            events.append(
                _event(
                    ReadEventKind.SCROLL_UP,
                    page,
                    page_index,
                    duration_ms=uniform_ms(rng, config.min_scroll_ms, config.max_scroll_ms),
                    viewport_index=i - 1,
                    viewport_count=n,
                    scroll_px=_scroll_px(config, rng, up=True),
                    detail="往回翻一点重看",
                )
            )
            prev = viewports[i - 1]
            events.append(
                _event(
                    ReadEventKind.READ_VIEWPORT,
                    page,
                    page_index,
                    duration_ms=max(280, reading_time_ms(prev.text, config, rng, i) // 2),
                    viewport_index=i - 1,
                    viewport_count=n,
                    chars=prev.char_count,
                    excerpt=prev.text,
                    detail=f"重读第 {i}/{n} 屏",
                )
            )
            events.append(
                _event(
                    ReadEventKind.SCROLL_DOWN,
                    page,
                    page_index,
                    duration_ms=uniform_ms(rng, config.min_scroll_ms, config.max_scroll_ms),
                    viewport_index=i,
                    viewport_count=n,
                    scroll_px=_scroll_px(config, rng, up=False),
                    detail="滚回刚才的位置",
                )
            )

        if i < n - 1:
            events.append(
                _event(
                    ReadEventKind.SCROLL_DOWN,
                    page,
                    page_index,
                    duration_ms=uniform_ms(rng, config.min_scroll_ms, config.max_scroll_ms),
                    viewport_index=i + 1,
                    viewport_count=n,
                    scroll_px=_scroll_px(config, rng, up=False),
                    detail=f"向下滚到第 {i + 2} 屏，不跳到文末",
                )
            )
        i += 1

    for diagram in page.diagrams:
        label = "拓扑图" if diagram.is_topology else "配图"
        caption = diagram.alt or diagram.caption or label
        events.append(
            _event(
                ReadEventKind.STUDY_DIAGRAM,
                page,
                page_index,
                duration_ms=uniform_ms(rng, config.diagram_ms_min, config.diagram_ms_max),
                viewport_count=n,
                viewport_index=n - 1,
                excerpt=caption,
                detail=f"查看{label}：{caption}",
                diagram_index=diagram.index,
            )
        )

    events.append(
        _event(
            ReadEventKind.SAVE_NOTES,
            page,
            page_index,
            duration_ms=uniform_ms(rng, config.notes_ms_min, config.notes_ms_max),
            viewport_count=n,
            viewport_index=n - 1,
            detail="整理这一页的笔记并保存，再考虑下一课",
        )
    )
    events.append(
        _event(
            ReadEventKind.DONE,
            page,
            page_index,
            duration_ms=uniform_ms(rng, 280, 900),
            viewport_count=n,
            viewport_index=n - 1,
            detail="这一课读完，停一下再翻页",
        )
    )
    return events


def plan_turn_page(
    from_page: PageContent,
    to_source: str,
    config: ReaderConfig,
    rng: random.Random,
    page_index: int,
) -> ReadEvent:
    return ReadEvent(
        kind=ReadEventKind.TURN_PAGE,
        page_index=page_index,
        source=from_page.source,
        duration_ms=uniform_ms(rng, config.inter_page_ms_min, config.inter_page_ms_max),
        viewport_count=len(from_page.viewports),
        detail=f"像点「下一课」一样打开下一页：{to_source}",
        page_title=from_page.title,
    )


def plan_stopped(
    source: str,
    page_index: int,
    reason: str,
    detail: str,
) -> ReadEvent:
    return ReadEvent(
        kind=ReadEventKind.STOPPED,
        page_index=page_index,
        source=source,
        duration_ms=0,
        detail=detail,
        stop_reason=reason,
    )


def _scroll_px(config: ReaderConfig, rng: random.Random, *, up: bool) -> int:
    base = config.viewport_px
    travel = int(base * rng.uniform(0.72, 0.92))
    return -travel if up else travel


def _event(
    kind: ReadEventKind,
    page: PageContent,
    page_index: int,
    *,
    duration_ms: int,
    viewport_count: int,
    detail: str,
    viewport_index: int | None = None,
    chars: int = 0,
    scroll_px: int = 0,
    excerpt: str = "",
    diagram_index: int | None = None,
) -> ReadEvent:
    shown = excerpt
    if len(shown) > 160:
        shown = shown[:159] + "…"
    return ReadEvent(
        kind=kind,
        page_index=page_index,
        source=page.source,
        duration_ms=duration_ms,
        viewport_index=viewport_index,
        viewport_count=viewport_count,
        chars=chars,
        scroll_px=scroll_px,
        detail=detail,
        excerpt=shown,
        page_title=page.title,
        diagram_index=diagram_index,
    )
