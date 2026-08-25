from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .clock import RecordingClock
from .config import ReaderConfig
from .fetch import FetchError, RobotsDisallowed
from .guard import stop_message
from .models import AccessStopped, ReadEvent, ReadEventKind
from .session import CourseReadSession, HumanReadSession, save_viewport_event, write_event_jsonl

_KIND_GLYPH = {
    ReadEventKind.OPEN: "▣",
    ReadEventKind.SETTLE: "…",
    ReadEventKind.READ_VIEWPORT: "👁",
    ReadEventKind.SCROLL_DOWN: "↓",
    ReadEventKind.SCROLL_UP: "↑",
    ReadEventKind.PAUSE: "⏸",
    ReadEventKind.IDLE: "☕",
    ReadEventKind.STUDY_DIAGRAM: "🖼",
    ReadEventKind.SAVE_NOTES: "✎",
    ReadEventKind.TURN_PAGE: "→",
    ReadEventKind.DONE: "✓",
    ReadEventKind.STOPPED: "■",
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "read":
        return _cmd_read(args)
    if args.command == "read-list":
        return _cmd_read_list(args)
    if args.command == "course":
        return _cmd_course(args)
    parser.print_help()
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="human_reader",
        description=(
            "像真实用户学课程一样阅读：从第一课起一页一页打开、读完正文和拓扑图、"
            "整理保存，再进入下一页。不并发、不批量预取、不绕过登录或验证码。"
        ),
    )
    sub = parser.add_subparsers(dest="command")

    course = sub.add_parser("course", help="从第一课开始，顺着「下一课」逐页阅读并保存为 Markdown")
    course.add_argument("start_url", help="第一课（或课程入口）的 URL / 本地 HTML")
    course.add_argument("--save-dir", required=True, help="笔记输出目录（每读完一课写一课）")
    course.add_argument("--cookies", default=None, help="浏览器导出的 Cookie 文件（Netscape 或 JSON）")
    course.add_argument("--storage-state", default=None, help="Playwright storage_state.json（登录后的会话）")
    course.add_argument("--resume", action="store_true", help="从 save-dir/state.json 记录的下一课继续")
    course.add_argument(
        "--browser",
        action="store_true",
        help="用同一浏览器标签页打开页面（适合 JS 课程平台）。仍是单页顺序阅读。",
    )
    course.add_argument(
        "--login-wait",
        action="store_true",
        help="打开浏览器后暂停，等你手动登录（含验证码）。脚本不会代填或绕过。",
    )
    course.add_argument(
        "--save-storage",
        default=None,
        help="手动登录成功后把会话写到这个 JSON，下次可直接 --storage-state 使用",
    )
    course.add_argument("--headed", action="store_true", help="显示浏览器窗口（--login-wait 默认开启）")
    _add_common_flags(course)

    read = sub.add_parser("read", help="依次阅读已知的本地文件 / URL 列表（仍是逐个打开）")
    read.add_argument("sources", nargs="+")
    read.add_argument("--save-dir", default=None, help="每读完一屏写入一个文本文件")
    _add_common_flags(read)

    read_list = sub.add_parser("read-list", help="按清单顺序阅读（一行一个来源，# 为注释）")
    read_list.add_argument("list_file")
    read_list.add_argument("--save-dir", default=None)
    _add_common_flags(read_list)
    return parser


def _add_common_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="时间倍率：1=真人节奏，10=十倍速预览，0=不等待但仍按动作顺序执行",
    )
    parser.add_argument("--seed", type=int, default=None, help="随机种子，便于复现同一次阅读轨迹")
    parser.add_argument("--viewport-chars", type=int, default=720, help="每一屏大约容纳的字符数")
    parser.add_argument("--max-pages", type=int, default=80, help="安全上限，防止一次读太久")
    parser.add_argument("--jsonl", default=None, help="把每个动作追加写入 JSONL 日志")
    parser.add_argument("--ignore-robots", action="store_true", help="跳过 robots.txt（仅用于你已获授权的课程）")
    parser.add_argument("--quiet", action="store_true", help="不在终端打印动作")
    parser.add_argument("--no-assets", action="store_true", help="只保存文字，不下载配图")


def _cmd_read(args: argparse.Namespace) -> int:
    return _run_sources(args.sources, args)


def _cmd_read_list(args: argparse.Namespace) -> int:
    path = Path(args.list_file)
    if not path.is_file():
        print(f"找不到清单文件：{path}", file=sys.stderr)
        return 2
    sources = _read_list_file(path)
    if not sources:
        print("清单是空的。", file=sys.stderr)
        return 2
    return _run_sources(sources, args)


def _read_list_file(path: Path) -> list[str]:
    sources: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        item = line.strip()
        if not item or item.startswith("#"):
            continue
        sources.append(item)
    return sources


def _cmd_course(args: argparse.Namespace) -> int:
    config = _config_from_args(args, save_dir=args.save_dir, course=True)
    clock = RecordingClock(actually_sleep=config.speed > 0)
    jsonl_path = Path(args.jsonl) if args.jsonl else None
    if jsonl_path and jsonl_path.exists():
        jsonl_path.unlink()
    save_dir = Path(args.save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    def on_event(event: ReadEvent) -> None:
        if jsonl_path is not None:
            write_event_jsonl(event, jsonl_path)
        if not args.quiet:
            _print_event(event, config)

    use_browser = bool(args.browser or args.login_wait)
    try:
        if use_browser:
            return _run_course_browser(args, config, clock, on_event, save_dir)
        session = CourseReadSession(config=config, clock=clock)
        events = list(
            session.read_course(
                args.start_url,
                on_event=on_event,
                resume_dir=save_dir if args.resume else None,
            )
        )
    except AccessStopped as exc:
        print(stop_message(exc, str(save_dir)), file=sys.stderr)
        return 3
    except RobotsDisallowed as exc:
        print(f"robots.txt 不允许访问：{exc}", file=sys.stderr)
        return 1
    except FetchError as exc:
        print(f"读取失败：{exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return _finish_status(events)


def _run_course_browser(args, config, clock, on_event, save_dir: Path) -> int:
    from .browser import BrowserCourseSession

    headed = True if args.login_wait else bool(args.headed)
    with BrowserCourseSession(config, headed=headed) as browser:
        if args.login_wait:
            browser.wait_for_manual_login(args.start_url, storage_out=args.save_storage)
        session = CourseReadSession(config=config, clock=clock, fetcher=browser)
        events = list(
            session.read_course(
                args.start_url,
                on_event=on_event,
                resume_dir=save_dir if args.resume else None,
            )
        )
    return _finish_status(events)


def _run_sources(sources: Sequence[str], args: argparse.Namespace) -> int:
    config = _config_from_args(args, save_dir=getattr(args, "save_dir", None), course=False)
    clock = RecordingClock(actually_sleep=config.speed > 0)
    session = HumanReadSession(config=config, clock=clock)
    save_dir = Path(args.save_dir) if getattr(args, "save_dir", None) else None
    jsonl_path = Path(args.jsonl) if args.jsonl else None
    if jsonl_path and jsonl_path.exists():
        jsonl_path.unlink()

    def on_event(event: ReadEvent) -> None:
        if save_dir is not None:
            save_viewport_event(event, save_dir)
        if jsonl_path is not None:
            write_event_jsonl(event, jsonl_path)
        if not args.quiet:
            _print_event(event, config)

    try:
        events = list(session.read(list(sources), on_event=on_event))
    except AccessStopped as exc:
        print(stop_message(exc, str(save_dir) if save_dir else None), file=sys.stderr)
        return 3
    except RobotsDisallowed as exc:
        print(f"robots.txt 不允许访问：{exc}", file=sys.stderr)
        print("若这是你已获授权的课程，可加 --ignore-robots。", file=sys.stderr)
        return 1
    except FetchError as exc:
        print(f"读取失败：{exc}", file=sys.stderr)
        return 1

    if not args.quiet:
        _print_summary(events)
    return _finish_status(events)


def _config_from_args(args: argparse.Namespace, save_dir: str | None, course: bool) -> ReaderConfig:
    cookies = getattr(args, "cookies", None)
    storage = getattr(args, "storage_state", None)
    return ReaderConfig(
        speed=max(0.0, args.speed),
        seed=args.seed,
        viewport_chars=args.viewport_chars,
        max_pages=args.max_pages,
        check_robots=not args.ignore_robots and not course,
        cookies_path=cookies,
        storage_state_path=storage,
        save_dir=save_dir,
        download_assets=not getattr(args, "no_assets", False),
    )


def _finish_status(events: list[ReadEvent]) -> int:
    if any(e.kind is ReadEventKind.STOPPED and e.stop_reason not in {"finished", "max_pages"} for e in events):
        return 3
    return 0


def _print_summary(events: list[ReadEvent]) -> None:
    reads = sum(1 for e in events if e.kind is ReadEventKind.READ_VIEWPORT)
    scrolls = sum(
        1 for e in events if e.kind in {ReadEventKind.SCROLL_DOWN, ReadEventKind.SCROLL_UP}
    )
    print(
        f"\n完成：{len(events)} 个动作，{reads} 次看屏，{scrolls} 次滚动；"
        "始终单线程、按页推进。",
        file=sys.stderr,
    )


def _print_event(event: ReadEvent, config: ReaderConfig) -> None:
    glyph = _KIND_GLYPH.get(event.kind, "·")
    shown_ms = config.scaled_ms(event.duration_ms)
    bar = _progress_bar(event)
    line = f"{glyph} {event.detail}  ({shown_ms}ms"
    if event.kind is ReadEventKind.READ_VIEWPORT:
        line += f", {event.chars}字"
    if event.scroll_px:
        line += f", {event.scroll_px:+d}px"
    line += ")"
    if bar:
        line = f"{bar} {line}"
    print(line)
    if event.kind is ReadEventKind.READ_VIEWPORT and event.excerpt:
        preview = event.excerpt.replace("\n", " ")
        if len(preview) > 96:
            preview = preview[:95] + "…"
        print(f"    「{preview}」")
    if event.kind is ReadEventKind.STOPPED:
        print(f"    stop_reason={event.stop_reason}", file=sys.stderr)


def _progress_bar(event: ReadEvent) -> str:
    if event.viewport_count <= 0 or event.viewport_index is None:
        return ""
    total = event.viewport_count
    filled = event.viewport_index + 1
    width = min(12, total)
    done = max(1, round(width * filled / total)) if filled else 0
    return "[" + "▓" * done + "░" * (width - done) + f" {filled}/{total}]"
