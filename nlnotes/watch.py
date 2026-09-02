"""盯 Grok 批量进度:开关自动续写,或每满一批把提示词拷到剪贴板。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from nlnotes.config import Config
from nlnotes.scan import select_items
from nlnotes.taskgen import failed_written_items, note_path, pending_items
from nlnotes.util import log, read_json

FLAG_NAME = "grok-auto-continue"
CONTINUE_PROMPT = Path(__file__).resolve().parents[1] / "prompts" / "61-继续下一批.md"


def flag_path(cfg: Config) -> Path:
    return cfg.build_dir / FLAG_NAME


def progress(cfg: Config) -> dict[str, int | list]:
    items = select_items(cfg, None, None, None)
    pending = pending_items(cfg, items)
    failed = failed_written_items(cfg, items)
    passed = 0
    written = 0
    for it in items:
        if note_path(cfg, it["id"]).exists():
            written += 1
        rep = cfg.report_dir() / f"{it['id']}.json"
        if rep.exists():
            try:
                if read_json(rep).get("passed"):
                    passed += 1
            except Exception:
                pass
    return {
        "total": len(items),
        "passed": passed,
        "written": written,
        "pending": len(pending),
        "failed": len(failed),
        "failed_ids": [it["id"] for it in failed],
        "next_ids": [it["id"] for it in pending[:5]],
        "auto_continue": flag_path(cfg).exists(),
    }


def enable(cfg: Config) -> Path:
    cfg.build_dir.mkdir(parents=True, exist_ok=True)
    p = flag_path(cfg)
    p.write_text("on\n", encoding="utf-8")
    return p


def disable(cfg: Config) -> None:
    p = flag_path(cfg)
    if p.exists():
        p.unlink()


def copy_clipboard(text: str) -> bool:
    if sys.platform != "win32":
        return False
    try:
        import subprocess
        subprocess.run(["clip"], input=text.encode("utf-16"), check=True)
        return True
    except Exception as exc:
        log(f"写入剪贴板失败: {exc}", "warn")
        return False


def beep() -> None:
    if sys.platform == "win32":
        try:
            import winsound
            winsound.MessageBeep()
            return
        except Exception:
            pass
    print("\a", end="", flush=True)


def continue_text() -> str:
    if CONTINUE_PROMPT.exists():
        return CONTINUE_PROMPT.read_text(encoding="utf-8").strip()
    return "请继续下一批:再连续做完接下来 5 章。规则同 prompts/60。"


def watch_batches(cfg: Config, batch: int, interval: float, clipboard: bool) -> int:
    prev = int(progress(cfg)["passed"])
    print(f"开始盯进度:已通过 {prev} 章。每再通过 {batch} 章提醒一次。"
          f"Ctrl+C 结束。")
    if clipboard:
        print("提醒时会把 prompts/61-继续下一批.md 拷到剪贴板,到 Cursor 里 Ctrl+V 即可。")
    print()
    try:
        while True:
            snap = progress(cfg)
            passed = int(snap["passed"])
            pending = int(snap["pending"])
            failed = int(snap["failed"])
            gained = passed - prev
            print(f"\r通过 {passed}/{snap['total']}  未写 {pending}  未过门禁 {failed}  "
                  f"本批 +{gained}/{batch}   ", end="", flush=True)
            if pending == 0 and failed == 0:
                print("\n全部通过。")
                return 0
            if gained >= batch:
                print()
                log(f"又通过了 {gained} 章", "ok")
                text = continue_text()
                if clipboard:
                    if copy_clipboard(text):
                        log("续写提示词已在剪贴板,切到 Cursor 按 Ctrl+V 发送", "ok")
                    else:
                        print(text)
                else:
                    print(text)
                beep()
                prev = passed
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n已停止盯进度。")
        return 0
