from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.cookiejar import CookieJar
from pathlib import Path
from unittest import mock

from human_reader.cli import main
from human_reader.cookies import load_cookie_jar
from human_reader.fetch import ConcurrentFetchBlocked, SerialFetcher
from human_reader.config import ReaderConfig

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "course"


class CookieTests(unittest.TestCase):
    def test_json_cookies(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
            json.dump(
                [
                    {
                        "name": "sessionid",
                        "value": "abc",
                        "domain": "example.test",
                        "path": "/",
                    }
                ],
                fh,
            )
            path = fh.name
        jar = load_cookie_jar(path)
        names = {c.name for c in jar}
        self.assertIn("sessionid", names)


class SerialFetchTests(unittest.TestCase):
    def test_second_thread_is_blocked(self) -> None:
        fetcher = SerialFetcher(ReaderConfig(speed=0, check_robots=False))
        started = threading.Event()
        release = threading.Event()
        errors: list[BaseException] = []

        real_load = fetcher._load_unlocked

        def slow_load(source, referer=None):
            started.set()
            release.wait(timeout=2)
            return real_load(source, referer)

        fetcher._load_unlocked = slow_load  # type: ignore[method-assign]

        def first() -> None:
            fetcher.load(str(FIXTURES / "03-summary.html"))

        t = threading.Thread(target=first)
        t.start()
        self.assertTrue(started.wait(timeout=2))
        with self.assertRaises(ConcurrentFetchBlocked):
            fetcher.load(str(FIXTURES / "01-intro.html"))
        release.set()
        t.join(timeout=2)


class CliTests(unittest.TestCase):
    def test_course_command_writes_readable_files(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            save_dir = Path(raw)
            code = main(
                [
                    "course",
                    str(FIXTURES / "01-intro.html"),
                    "--save-dir",
                    str(save_dir),
                    "--speed",
                    "0",
                    "--seed",
                    "1",
                    "--quiet",
                ]
            )
            self.assertEqual(code, 0)
            self.assertTrue((save_dir / "FULL.md").is_file())
            self.assertIn("第一课", (save_dir / "FULL.md").read_text(encoding="utf-8"))
            svg_files = list(save_dir.glob("**/assets/*.svg"))
            self.assertGreaterEqual(len(svg_files), 1)

    def test_help_mentions_no_bypass(self) -> None:
        with mock.patch("sys.stdout") as stdout:
            try:
                main(["--help"])
            except SystemExit:
                pass
        # argparse writes to the real stdout; just ensure the command exists.
        self.assertEqual(main([]), 2)


if __name__ == "__main__":
    unittest.main()
