"""命令行入口:python -m nlnotes <子命令>"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from nlnotes import __version__
from nlnotes.config import DEFAULT_CONFIG_PATH, load_config
from nlnotes.util import log, read_json


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--config", help="配置文件路径(默认 config/pipeline.json)")
    p.add_argument("--source-root", help="课程根目录,覆盖配置(如 D:/NetworkLessons/All-Courses-v3.0)")
    p.add_argument("--notes-dir", help="笔记输出目录,覆盖配置")
    p.add_argument("--build-dir", help="中间产物目录,覆盖配置")


def _select(p: argparse.ArgumentParser) -> None:
    p.add_argument("--id", nargs="*", dest="ids", help="只处理指定 pdf_id(支持前缀)")
    p.add_argument("--path", dest="filter_path", help="按相对路径关键字筛选,如 OSPF")
    p.add_argument("--limit", type=int, help="最多处理前 N 个")
    p.add_argument("--all", action="store_true", help="处理全部(默认行为)")


def _cfg(args: argparse.Namespace):
    return load_config(args.config, {
        "source_root": getattr(args, "source_root", None),
        "notes_dir": getattr(args, "notes_dir", None),
        "build_dir": getattr(args, "build_dir", None),
    })


# ------------------------------------------------------------------ 子命令

def cmd_doctor(args) -> int:
    cfg = _cfg(args)
    print(f"nlnotes {__version__}")
    print(f"配置文件      : {cfg.path or '(使用内置默认值)'}")
    print(f"课程根目录    : {cfg.source_root}  "
          f"{'✅ 存在' if cfg.source_root.exists() else '❌ 不存在'}")
    print(f"笔记输出目录  : {cfg.notes_dir}")
    print(f"中间产物目录  : {cfg.build_dir}")
    ok = cfg.source_root.exists()

    print("\n必需依赖:")
    for mod, why in (("pymupdf", "PDF 抽取 (pymupdf)"), ("PIL", "动画/静态图 (Pillow)"),
                     ("jinja2", "Markdown 渲染"), ("rapidfuzz", "原文引用比对"),
                     ("jsonschema", "结构校验")):
        try:
            __import__(mod)
            print(f"  ✅ {mod:<12} {why}")
        except ImportError:
            print(f"  ❌ {mod:<12} {why}  -> pip install -r requirements.txt")
            ok = False

    print("\n可选外部工具(缺失时自动降级,不影响流水线):")
    for exe, why, fallback in (
        (str(cfg["mermaid_cli"]), "mermaid 图渲染成 PNG", "内联 mermaid 代码块"),
        (str(cfg["dot_cmd"]), "graphviz 图渲染成 PNG", "内联 dot 代码块"),
        (str(cfg["ffmpeg_cmd"]), "额外输出 MP4", "只输出 GIF + 静态图"),
    ):
        found = shutil.which(exe)
        print(f"  {'✅' if found else '➖'} {exe:<12} {why}"
              + ("" if found else f"(缺失 → {fallback})"))

    from nlnotes.visuals import find_font
    font = find_font(cfg)
    print(f"\n中文字体      : {font or '❌ 未找到(自制图中文会变方块)'}")
    if not font:
        print("  -> 在 config/pipeline.json 设置 font_path,例如 C:/Windows/Fonts/msyh.ttc")
        ok = False

    provider = str(cfg["illustration_provider"])
    print(f"AI 示意图     : provider={provider}"
          + ("(未启用,packet_flow/mermaid 已足够用)" if provider == "none" else ""))
    print("\n" + ("✅ 环境就绪" if ok else "⚠️ 存在问题,请按上面的提示处理"))
    return 0 if ok else 1


def cmd_scan(args) -> int:
    from nlnotes.scan import scan
    m = scan(_cfg(args), force=args.force)
    for cat in m["categories"]:
        n = sum(1 for it in m["items"] if it["course_path"] and it["course_path"][0] == cat)
        print(f"  {cat}: {n} 个 PDF")
    return 0


def cmd_extract(args) -> int:
    from nlnotes.extract import extract_many
    from nlnotes.scan import select_items
    cfg = _cfg(args)
    items = select_items(cfg, args.ids, args.filter_path, args.limit)
    log(f"待抽取 {len(items)} 个 PDF")
    extract_many(cfg, items, force=args.force)
    return 0


def cmd_tasks(args) -> int:
    from nlnotes.scan import select_items
    from nlnotes.taskgen import build_tasks
    cfg = _cfg(args)
    items = select_items(cfg, args.ids, args.filter_path, args.limit)
    build_tasks(cfg, items, force=args.force)
    return 0


def cmd_next(args) -> int:
    from nlnotes.scan import select_items
    from nlnotes.taskgen import pending_items
    cfg = _cfg(args)
    items = select_items(cfg, args.ids, args.filter_path, None)
    pending = pending_items(cfg, items)
    if not pending:
        print("🎉 所有 PDF 都已产出 note.json。")
        return 0
    print(f"剩余 {len(pending)} 个待撰写,接下来 {min(args.count, len(pending))} 个:\n")
    for it in pending[:args.count]:
        task = cfg.task_dir(it["id"]) / "TASK.md"
        state = "任务包已就绪" if task.exists() else "⚠️ 任务包缺失,先跑 tasks"
        print(f"- id: {it['id']}\n  课程: {it['course_path_display']}\n"
              f"  标题: {it['title']}\n  任务: {task}  ({state})\n")
    return 0


def cmd_verify(args) -> int:
    from nlnotes.scan import select_items
    from nlnotes.verify import format_report, verify_note
    cfg = _cfg(args)
    items = select_items(cfg, args.ids, args.filter_path, args.limit)
    failed = 0
    for it in items:
        rep = verify_note(cfg, it["id"])
        if not rep.passed:
            failed += 1
        if args.show or not rep.passed:
            print(format_report(rep))
    return 1 if failed else 0


def cmd_assemble(args) -> int:
    from nlnotes.assemble import assemble_one, build_index
    from nlnotes.scan import select_items
    cfg = _cfg(args)
    items = select_items(cfg, args.ids, args.filter_path, args.limit)
    for it in items:
        try:
            assemble_one(cfg, it)
        except Exception as exc:
            log(f"组装失败 {it['rel_path']}: {exc}", "error")
    build_index(cfg)
    return 0


def cmd_build(args) -> int:
    """校验 -> 渲染 -> 组装。校验不过默认拒绝出笔记。"""
    from nlnotes.assemble import assemble_one, build_index
    from nlnotes.scan import select_items
    from nlnotes.verify import format_report, verify_note
    cfg = _cfg(args)
    items = select_items(cfg, args.ids, args.filter_path, args.limit)
    failed: list[str] = []
    for it in items:
        rep = verify_note(cfg, it["id"])
        if not rep.passed:
            print(format_report(rep))
            failed.append(it["id"])
            if not args.force:
                log(f"{it['id']} 未通过校验,跳过生成(如需强制生成加 --force)", "warn")
                continue
        try:
            assemble_one(cfg, it, verified=rep.passed, stats=rep.stats)
        except Exception as exc:
            log(f"组装失败 {it['rel_path']}: {exc}", "error")
            failed.append(it["id"])
    build_index(cfg)
    if failed:
        log(f"{len(failed)} 个未通过: {', '.join(failed[:10])}", "warn")
        return 1
    return 0


def cmd_prepare(args) -> int:
    """一条命令跑完准备阶段:scan -> extract -> tasks。"""
    from nlnotes.extract import extract_many
    from nlnotes.scan import scan, select_items
    from nlnotes.taskgen import build_tasks
    cfg = _cfg(args)
    scan(cfg, force=args.force)
    items = select_items(cfg, args.ids, args.filter_path, args.limit)
    extract_many(cfg, items, force=args.force)
    build_tasks(cfg, items, force=args.force)
    print(f"\n准备完成。共 {len(items)} 个任务包位于 {cfg.build_dir / 'tasks'}")
    print("下一步:让 AI 逐个读取 TASK.md 产出 note.json,然后 python -m nlnotes build --id <id>")
    return 0


def cmd_status(args) -> int:
    from nlnotes.scan import select_items
    from nlnotes.taskgen import note_path
    cfg = _cfg(args)
    items = select_items(cfg, args.ids, args.filter_path, None)
    counts = {"未开始": 0, "已抽取": 0, "任务就绪": 0, "已撰写": 0, "已校验": 0, "已发布": 0}
    rows = []
    for it in items:
        st = "未开始"
        if (cfg.extract_dir(it["id"]) / "extract.json").exists():
            st = "已抽取"
        if (cfg.task_dir(it["id"]) / "TASK.md").exists():
            st = "任务就绪"
        if note_path(cfg, it["id"]).exists():
            st = "已撰写"
        rep = cfg.report_dir() / f"{it['id']}.json"
        if rep.exists() and read_json(rep).get("passed"):
            st = "已校验"
        if (cfg.notes_dir / it["note_rel_path"]).exists() and st == "已校验":
            st = "已发布"
        counts[st] += 1
        rows.append((st, it["id"], it["course_path_display"], it["title"]))

    print(f"共 {len(items)} 个 PDF")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    if args.detail:
        print()
        for st, pid, cat, title in rows:
            print(f"  [{st:<6}] {pid}  {cat} / {title}")
    return 0


def cmd_init(args) -> int:
    """把示例配置复制成 config/pipeline.json。"""
    example = DEFAULT_CONFIG_PATH.parent / "pipeline.example.json"
    if DEFAULT_CONFIG_PATH.exists() and not args.force:
        print(f"{DEFAULT_CONFIG_PATH} 已存在(加 --force 覆盖)")
        return 0
    DEFAULT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(example, DEFAULT_CONFIG_PATH)
    print(f"已生成 {DEFAULT_CONFIG_PATH},请修改 source_root 为你的课程目录。")
    return 0


# ------------------------------------------------------------------ 解析

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m nlnotes",
        description="NetworkLessons 英文 PDF -> 有图/有动画/有费曼测验的中文笔记")
    p.add_argument("--version", action="version", version=f"nlnotes {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("init", help="生成 config/pipeline.json")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("doctor", help="体检:依赖、字体、路径")
    _common(sp)
    sp.set_defaults(func=cmd_doctor)

    sp = sub.add_parser("scan", help="扫描课程目录树")
    _common(sp)
    sp.add_argument("--force", action="store_true", help="强制重算文件哈希")
    sp.set_defaults(func=cmd_scan)

    sp = sub.add_parser("extract", help="抽取原文/图片/结构")
    _common(sp)
    _select(sp)
    sp.add_argument("--force", action="store_true", help="忽略缓存重新抽取")
    sp.set_defaults(func=cmd_extract)

    sp = sub.add_parser("tasks", help="生成 AI 任务包")
    _common(sp)
    _select(sp)
    sp.add_argument("--force", action="store_true", help="重置 note.template.json")
    sp.set_defaults(func=cmd_tasks)

    sp = sub.add_parser("prepare", help="scan + extract + tasks 一条龙")
    _common(sp)
    _select(sp)
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_prepare)

    sp = sub.add_parser("next", help="列出接下来要写的章节")
    _common(sp)
    _select(sp)
    sp.add_argument("--count", type=int, default=3)
    sp.set_defaults(func=cmd_next)

    sp = sub.add_parser("verify", help="校验 note.json(反臆想门禁)")
    _common(sp)
    _select(sp)
    sp.add_argument("--show", action="store_true", help="通过时也打印报告")
    sp.set_defaults(func=cmd_verify)

    sp = sub.add_parser("assemble", help="只组装 Markdown(跳过校验)")
    _common(sp)
    _select(sp)
    sp.set_defaults(func=cmd_assemble)

    sp = sub.add_parser("build", help="校验 + 渲染 + 组装(推荐)")
    _common(sp)
    _select(sp)
    sp.add_argument("--force", action="store_true", help="校验不通过也强行生成")
    sp.set_defaults(func=cmd_build)

    sp = sub.add_parser("index", help="重建 notes/README.md 索引")
    _common(sp)
    sp.set_defaults(func=lambda a: (__import__("nlnotes.assemble", fromlist=["build_index"])
                                    .build_index(_cfg(a)), 0)[1])

    sp = sub.add_parser("status", help="查看整体进度")
    _common(sp)
    _select(sp)
    sp.add_argument("--detail", action="store_true")
    sp.set_defaults(func=cmd_status)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except (FileNotFoundError, KeyError, ValueError) as exc:
        log(str(exc), "error")
        return 2
    except KeyboardInterrupt:
        log("已中断", "warn")
        return 130


if __name__ == "__main__":
    sys.exit(main())
