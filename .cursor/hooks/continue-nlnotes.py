"""Cursor stop hook: Grok 停下来后,若开了自动续写且还有未写章节,再发同一段提示词.

默认关闭.只有 build/grok-auto-continue 这个开关文件存在时才会续写,
所以普通问答、Cloud Agent 不会被带着跑.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FLAG = ROOT / "build" / "grok-auto-continue"
PROMPT_PATH = ROOT / "prompts" / "61-继续下一批.md"


def _out(obj: dict) -> None:
    data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def _continue_prompt() -> str:
    if PROMPT_PATH.exists():
        return PROMPT_PATH.read_text(encoding="utf-8").strip()
    return ("请继续下一批:再连续做完接下来 5 章中文笔记。"
            "规则同 prompts/60-批量流水作业.md。"
            "若 next 没有输出就停下来汇报,不要空转,不要改门禁。")


def main() -> None:
    raw = sys.stdin.read() if not sys.stdin.isatty() else "{}"
    try:
        event = json.loads(raw or "{}")
    except json.JSONDecodeError:
        _out({})
        return
    if event.get("status") != "completed":
        _out({})
        return
    if not FLAG.exists():
        _out({})
        return

    sys.path.insert(0, str(ROOT))
    try:
        from nlnotes.config import load_config
        from nlnotes.scan import select_items
        from nlnotes.taskgen import failed_written_items, pending_items
        cfg = load_config(ROOT / "config" / "pipeline.json")
        items = select_items(cfg, None, None, None)
        pending = pending_items(cfg, items)
        failed = failed_written_items(cfg, items)
    except Exception as exc:
        sys.stderr.write(f"[nlnotes continue] 无法读取进度,本轮不续写: {exc}\n")
        _out({})
        return

    if pending:
        sys.stderr.write(f"[nlnotes continue] 还剩 {len(pending)} 章未写,自动续下一批 5 章\n")
        _out({"followup_message": _continue_prompt()})
        return

    FLAG.unlink(missing_ok=True)
    if failed:
        ids = "\n".join(f"- {it['id']}  {it['title']}" for it in failed[:20])
        _out({"followup_message": (
            "未写的章节已经没有了,自动续写到此结束。\n"
            f"还有 {len(failed)} 章已写出 note.json 但门禁未通过,请列出来然后停,不要再 next:\n"
            f"{ids}\n"
            "补写必须点名 id,不要用 next。"
        )})
        return
    _out({})


if __name__ == "__main__":
    main()
