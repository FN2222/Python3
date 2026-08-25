from __future__ import annotations

import unittest
from pathlib import Path

from human_reader.clock import RecordingClock
from human_reader.config import ReaderConfig
from human_reader.fetch import SerialFetcher
from human_reader.guard import inspect_http_status, inspect_page
from human_reader.models import AccessStopped, ReadEventKind, StopReason
from human_reader.navigate import find_next_url
from human_reader.planner import plan_page
from human_reader.session import CourseReadSession, HumanReadSession

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "course"


class GuardTests(unittest.TestCase):
    def test_http_403_and_429_stop(self) -> None:
        with self.assertRaises(AccessStopped) as ctx:
            inspect_http_status(403, "https://example.test/lesson/2")
        self.assertEqual(ctx.exception.reason, StopReason.PERMISSION)
        with self.assertRaises(AccessStopped) as ctx:
            inspect_http_status(429, "https://example.test/lesson/2")
        self.assertEqual(ctx.exception.reason, StopReason.RATE_LIMIT)

    def test_login_page_stops(self) -> None:
        html = (FIXTURES / "login.html").read_text(encoding="utf-8")
        with self.assertRaises(AccessStopped) as ctx:
            inspect_page(html, "https://example.test/login", "请先登录 登录后才能查看课程内容")
        self.assertEqual(ctx.exception.reason, StopReason.LOGIN_REQUIRED)

    def test_captcha_page_stops(self) -> None:
        html = (FIXTURES / "captcha.html").read_text(encoding="utf-8")
        with self.assertRaises(AccessStopped) as ctx:
            inspect_page(html, "https://example.test/lesson/2", "请完成验证码后再继续访问")
        self.assertEqual(ctx.exception.reason, StopReason.CAPTCHA)

    def test_course_text_mentioning_captcha_does_not_stop(self) -> None:
        html = (FIXTURES / "01-intro.html").read_text(encoding="utf-8")
        inspect_page(html, "https://example.test/lesson/1", "遇到登录验证、验证码、403 或 429，立刻停止" * 20)


class NavigateTests(unittest.TestCase):
    def test_prefers_rel_next(self) -> None:
        html = (FIXTURES / "01-intro.html").read_text(encoding="utf-8")
        base = (FIXTURES / "01-intro.html").resolve().as_uri()
        nxt = find_next_url(html, base, base)
        self.assertIsNotNone(nxt)
        self.assertTrue(nxt.endswith("02-routing.html"))

    def test_last_page_has_no_next(self) -> None:
        html = (FIXTURES / "03-summary.html").read_text(encoding="utf-8")
        base = (FIXTURES / "03-summary.html").resolve().as_uri()
        self.assertIsNone(find_next_url(html, base, base))


class PlannerTests(unittest.TestCase):
    def test_never_reads_whole_document_in_one_action(self) -> None:
        from human_reader.fetch import load_page

        page = load_page(str(FIXTURES / "01-intro.html"), ReaderConfig(viewport_chars=240, seed=0))
        self.assertGreater(len(page.viewports), 1)
        events = plan_page(page, ReaderConfig(seed=0), __import__("random").Random(0), 0)
        reads = [e for e in events if e.kind is ReadEventKind.READ_VIEWPORT]
        self.assertGreater(len(reads), 1)
        total = sum(vp.char_count for vp in page.viewports)
        for event in reads:
            self.assertLess(event.chars, total)
        kinds = [e.kind for e in events]
        self.assertEqual(kinds[0], ReadEventKind.OPEN)
        self.assertIn(ReadEventKind.SCROLL_DOWN, kinds)
        self.assertIn(ReadEventKind.STUDY_DIAGRAM, kinds)
        self.assertIn(ReadEventKind.SAVE_NOTES, kinds)
        self.assertEqual(kinds[-1], ReadEventKind.DONE)
        self.assertLess(kinds.index(ReadEventKind.SAVE_NOTES), kinds.index(ReadEventKind.DONE))
        self.assertLess(kinds.index(ReadEventKind.STUDY_DIAGRAM), kinds.index(ReadEventKind.SAVE_NOTES))


class CourseSessionTests(unittest.TestCase):
    def test_reads_lessons_one_by_one_then_saves(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            save_dir = Path(raw)
            config = ReaderConfig(
                speed=0,
                seed=1,
                save_dir=str(save_dir),
                check_robots=False,
                viewport_chars=360,
            )
            fetcher = _LoggingFetcher(config)
            session = CourseReadSession(config, clock=RecordingClock(actually_sleep=False), fetcher=fetcher)
            events = list(session.read_course(str(FIXTURES / "01-intro.html")))
            names = [Path(u).name for u in fetcher.order]
            self.assertEqual(names, ["01-intro.html", "02-routing.html", "03-summary.html"])
            self.assertTrue(any(e.kind is ReadEventKind.TURN_PAGE for e in events))
            self.assertTrue(any(e.stop_reason == "finished" for e in events))
            self.assertTrue((save_dir / "README.md").is_file())
            self.assertTrue((save_dir / "FULL.md").is_file())
            lesson_dirs = [p for p in save_dir.iterdir() if p.is_dir()]
            self.assertEqual(len(lesson_dirs), 3)
            full = (save_dir / "FULL.md").read_text(encoding="utf-8")
            self.assertIn("第一课", full)
            self.assertIn("第二课", full)
            self.assertIn("第三课", full)
            self.assertIn("拓扑", (save_dir / "README.md").read_text(encoding="utf-8") + full)

    def test_stop_on_access_keeps_previous_notes(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            save_dir = Path(raw)
            config = ReaderConfig(speed=0, seed=1, save_dir=str(save_dir), viewport_chars=400)
            fetcher = _StopOnSecondFetcher()
            session = CourseReadSession(config, clock=RecordingClock(actually_sleep=False), fetcher=fetcher)
            events = list(session.read_course("lesson://1"))
            self.assertEqual(fetcher.order, ["lesson://1", "lesson://2"])
            stopped = [e for e in events if e.kind is ReadEventKind.STOPPED]
            self.assertEqual(len(stopped), 1)
            self.assertEqual(stopped[0].stop_reason, StopReason.PERMISSION.value)
            self.assertTrue(any(e.kind is ReadEventKind.SAVE_NOTES for e in events))
            self.assertTrue((save_dir / "state.json").is_file())
            state = (save_dir / "state.json").read_text(encoding="utf-8")
            self.assertIn("permission", state)

    def test_known_list_is_still_serial(self) -> None:
        sources = [
            str(FIXTURES / "01-intro.html"),
            str(FIXTURES / "03-summary.html"),
        ]
        session = HumanReadSession(
            ReaderConfig(speed=0, seed=2, viewport_chars=400),
            clock=RecordingClock(actually_sleep=False),
        )
        events = list(session.read(sources))
        pages = [e.page_index for e in events if e.kind is ReadEventKind.OPEN]
        self.assertEqual(pages, [0, 1])
        self.assertTrue(any(e.kind is ReadEventKind.TURN_PAGE for e in events))


class _LoggingFetcher(SerialFetcher):
    def __init__(self, config: ReaderConfig) -> None:
        super().__init__(config)
        self.order: list[str] = []

    def load(self, source: str, referer: str | None = None):
        self.order.append(source)
        return super().load(source, referer)


class _StopOnSecondFetcher:
    def __init__(self) -> None:
        from human_reader.models import Diagram, PageContent, Viewport

        self.order: list[str] = []
        self._PageContent = PageContent
        self._Viewport = Viewport
        self._Diagram = Diagram

    def load(self, source: str, referer: str | None = None):
        del referer
        self.order.append(source)
        if source.endswith("2"):
            raise AccessStopped(StopReason.PERMISSION, "HTTP 403", status_code=403, url=source)
        return self._PageContent(
            source=source,
            title="第一课",
            text="这一页已经完整阅读，包含足够的文字用来分页保存。" * 8,
            viewports=[
                self._Viewport(0, "首屏文字", 4, 0, 4),
                self._Viewport(1, "第二屏文字", 5, 4, 9),
            ],
            diagrams=[],
            next_url="lesson://2",
            final_url=source,
        )

    def load_bytes(self, url: str, referer: str | None = None):
        del url, referer
        raise AssertionError("no asset fetch expected")


if __name__ == "__main__":
    unittest.main()
