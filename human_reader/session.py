from __future__ import annotations

import json
import random
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from urllib.parse import urlparse

from .clock import Clock
from .config import ReaderConfig
from .export import (
    lesson_folder,
    load_state,
    save_asset_bytes,
    update_index,
    write_lesson,
)
from .fetch import SerialFetcher, load_page
from .models import AccessStopped, Diagram, PageContent, ReadEvent, ReadEventKind, StopReason
from .planner import plan_page, plan_stopped, plan_turn_page
from .timing import uniform_ms

EventCallback = Callable[[ReadEvent], None]


class HumanReadSession:
    """Read known sources one page, one viewport at a time."""

    def __init__(
        self,
        config: ReaderConfig | None = None,
        clock: Clock | None = None,
        loader: Callable[[str, ReaderConfig], PageContent] | None = None,
    ) -> None:
        self.config = config or ReaderConfig()
        self.clock = clock or Clock()
        self.loader = loader or load_page
        self._busy = False
        self._rng = random.Random(self.config.seed)

    def read(self, sources: Sequence[str], on_event: EventCallback | None = None) -> Iterator[ReadEvent]:
        if self._busy:
            raise RuntimeError("this session is already reading; start another session instead of overlapping")
        if not sources:
            return
        capped = list(sources)[: self.config.max_pages]
        self._busy = True
        try:
            yield from self._read_serial(capped, on_event)
        finally:
            self._busy = False

    def collect_text_after_reading(self, events: Sequence[ReadEvent]) -> dict[str, str]:
        pages: dict[int, dict[int, str]] = {}
        sources: dict[int, str] = {}
        for event in events:
            sources[event.page_index] = event.source
            if event.kind is not ReadEventKind.READ_VIEWPORT:
                continue
            if event.viewport_index is None:
                continue
            pages.setdefault(event.page_index, {})[event.viewport_index] = event.excerpt
        merged: dict[str, str] = {}
        for page_index in sorted(pages):
            chunks = pages[page_index]
            ordered = [chunks[i] for i in sorted(chunks)]
            merged[sources[page_index]] = "\n\n".join(ordered)
        return merged

    def _read_serial(
        self,
        sources: list[str],
        on_event: EventCallback | None,
    ) -> Iterator[ReadEvent]:
        previous: PageContent | None = None
        for page_index, source in enumerate(sources):
            if previous is not None:
                turn = plan_turn_page(
                    previous, source, self.config, self._rng, page_index - 1
                )
                yield from self._emit(turn, on_event)
            page = self.loader(source, self.config)
            for event in plan_page(page, self.config, self._rng, page_index):
                yield from self._emit(event, on_event)
            previous = page

    def _emit(self, event: ReadEvent, on_event: EventCallback | None) -> Iterator[ReadEvent]:
        wait_ms = self.config.scaled_ms(event.duration_ms)
        self.clock.sleep_ms(wait_ms)
        if on_event is not None:
            on_event(event)
        yield event


class CourseReadSession:
    """Start at lesson one. Finish a page (text + diagrams + notes) before the next.

    Never fans out into parallel chapter fetches. Access-control pages stop the run.
    """

    def __init__(
        self,
        config: ReaderConfig | None = None,
        clock: Clock | None = None,
        fetcher: SerialFetcher | None = None,
    ) -> None:
        self.config = config or ReaderConfig()
        self.clock = clock or Clock()
        self.fetcher = fetcher or SerialFetcher(self.config)
        self._busy = False
        self._rng = random.Random(self.config.seed)
        self.saved_entries: list[dict] = []

    def read_course(
        self,
        start_url: str,
        on_event: EventCallback | None = None,
        resume_dir: Path | None = None,
    ) -> Iterator[ReadEvent]:
        if self._busy:
            raise RuntimeError("this session is already reading")
        self._busy = True
        try:
            yield from self._run(start_url, on_event, resume_dir)
        finally:
            self._busy = False

    def _run(
        self,
        start_url: str,
        on_event: EventCallback | None,
        resume_dir: Path | None,
    ) -> Iterator[ReadEvent]:
        save_dir = self.config.output_dir()
        seen: set[str] = set()
        entries: list[dict] = []
        url = start_url
        page_index = 0
        referer = None

        if resume_dir is not None:
            state = load_state(resume_dir)
            entries = list(state.get("entries") or [])
            seen = {item.get("final_url") or item.get("source") for item in entries if item}
            seen.discard(None)
            stopped = state.get("stopped") or {}
            page_index = len(entries)
            if entries:
                referer = entries[-1].get("final_url")
            if stopped.get("reason") == StopReason.FINISHED.value:
                yield from self._emit(
                    plan_stopped(
                        (entries[-1].get("source") if entries else start_url) or start_url,
                        page_index,
                        StopReason.FINISHED.value,
                        "上次已经读到没有「下一课」的页面，没有更多内容可继续。",
                    ),
                    on_event,
                )
                return
            if stopped.get("url"):
                url = stopped["url"]
                seen.discard(url)
            elif entries:
                url = entries[-1].get("next_url") or start_url
                if not entries[-1].get("next_url"):
                    yield from self._emit(
                        plan_stopped(
                            entries[-1].get("source") or start_url,
                            page_index,
                            StopReason.FINISHED.value,
                            "上次已经读到没有「下一课」的页面，没有更多内容可继续。",
                        ),
                        on_event,
                    )
                    return

        while url and page_index < self.config.max_pages:
            norm = url
            if norm in seen:
                yield from self._emit(
                    plan_stopped(url, page_index, StopReason.LOOP.value, "下一课链接回到已读页面，停止以免循环刷新。"),
                    on_event,
                )
                if save_dir:
                    update_index(save_dir, entries, {"reason": "loop", "detail": "下一课形成循环", "url": url})
                return
            seen.add(norm)

            try:
                page = self.fetcher.load(url, referer=referer)
            except AccessStopped as exc:
                yield from self._handle_stop(exc, url, page_index, entries, save_dir, on_event)
                return

            for event in plan_page(page, self.config, self._rng, page_index):
                if event.kind is ReadEventKind.STUDY_DIAGRAM and self.config.download_assets and save_dir:
                    self._save_one_diagram(page, event, save_dir, page_index)
                if event.kind is ReadEventKind.SAVE_NOTES and save_dir:
                    lesson_path = write_lesson(page, save_dir, page_index, page.diagrams)
                    rel = str(lesson_path.relative_to(save_dir))
                    event = ReadEvent(
                        kind=event.kind,
                        page_index=event.page_index,
                        source=event.source,
                        duration_ms=event.duration_ms,
                        viewport_index=event.viewport_index,
                        viewport_count=event.viewport_count,
                        detail=f"整理并保存：{rel}",
                        page_title=event.page_title,
                        saved_path=rel,
                    )
                    entry = {
                        "index": page_index,
                        "title": page.title,
                        "source": page.source,
                        "final_url": page.final_url,
                        "next_url": page.next_url,
                        "path": rel,
                    }
                    entries.append(entry)
                    update_index(save_dir, entries)
                    self.saved_entries = entries
                yield from self._emit(event, on_event)

            referer = page.final_url or url
            if not page.next_url:
                yield from self._emit(
                    plan_stopped(
                        page.final_url,
                        page_index,
                        StopReason.FINISHED.value,
                        "没有「下一课 / 下一页」链接，按顺序读完了当前这条学习路径。",
                    ),
                    on_event,
                )
                return

            turn = plan_turn_page(page, page.next_url, self.config, self._rng, page_index)
            yield from self._emit(turn, on_event)
            url = page.next_url
            page_index += 1

        if url and page_index >= self.config.max_pages:
            yield from self._emit(
                plan_stopped(
                    url,
                    page_index,
                    StopReason.MAX_PAGES.value,
                    f"已达到 max_pages={self.config.max_pages}，停止以免一次读太久。可用 --resume 从下一课继续。",
                ),
                on_event,
            )
            if save_dir:
                update_index(
                    save_dir,
                    entries,
                    {
                        "reason": "max_pages",
                        "detail": f"达到上限 {self.config.max_pages}",
                        "url": url,
                    },
                )

    def _save_one_diagram(
        self,
        page: PageContent,
        event: ReadEvent,
        save_dir: Path,
        page_index: int,
    ) -> None:
        if event.diagram_index is None or event.diagram_index >= len(page.diagrams):
            return
        diagram = page.diagrams[event.diagram_index]
        folder = lesson_folder(save_dir, page, page_index)
        if diagram.inline_svg:
            # Inline SVG is written with the lesson notes; nothing extra to fetch.
            return
        if not diagram.src or diagram.src == "inline-svg":
            return
        if _as_data_or_local(diagram, folder):
            return
        gap = uniform_ms(self._rng, self.config.asset_gap_ms_min, self.config.asset_gap_ms_max)
        self.clock.sleep_ms(self.config.scaled_ms(gap))
        data, content_type = self.fetcher.load_bytes(diagram.src, referer=page.final_url)
        save_asset_bytes(folder, diagram, data, content_type)

    def _handle_stop(
        self,
        exc: AccessStopped,
        url: str,
        page_index: int,
        entries: list[dict],
        save_dir: Path | None,
        on_event: EventCallback | None,
    ) -> Iterator[ReadEvent]:
        if save_dir:
            update_index(
                save_dir,
                entries,
                {"reason": exc.reason.value, "detail": exc.message, "url": exc.url or url},
            )
        yield from self._emit(
            plan_stopped(url, page_index, exc.reason.value, exc.message),
            on_event,
        )

    def _emit(self, event: ReadEvent, on_event: EventCallback | None) -> Iterator[ReadEvent]:
        wait_ms = self.config.scaled_ms(event.duration_ms)
        self.clock.sleep_ms(wait_ms)
        if on_event is not None:
            on_event(event)
        yield event


def _as_data_or_local(diagram: Diagram, folder: Path) -> bool:
    src = diagram.src
    if src.startswith("data:"):
        return True
    parsed = urlparse(src)
    if parsed.scheme in {"", "file"}:
        from pathlib import Path as P

        path = P(parsed.path or src)
        if path.is_file():
            data = path.read_bytes()
            save_asset_bytes(folder, diagram, data, None)
            return True
    return False


def save_viewport_event(event: ReadEvent, save_dir: Path) -> Path | None:
    if event.kind is not ReadEventKind.READ_VIEWPORT:
        return None
    if event.viewport_index is None:
        return None
    save_dir.mkdir(parents=True, exist_ok=True)
    path = save_dir / f"page{event.page_index:02d}_vp{event.viewport_index:02d}.txt"
    path.write_text(event.excerpt, encoding="utf-8")
    return path


def write_event_jsonl(event: ReadEvent, jsonl_path: Path) -> None:
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    payload = event.as_dict()
    if len(payload["excerpt"]) > 160:
        payload["excerpt"] = payload["excerpt"][:159] + "…"
    with jsonl_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
