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


def cmd_diag(args) -> int:
    from nlnotes.diag import diagnose
    cfg = _cfg(args)
    out = diagnose(cfg, sample=args.sample)
    print(f"\n请把这个文件的内容发给协助调参的人:\n  {out}\n")
    print("它包含:环境与依赖、课程目录概况、PDF 体检汇总、抽取质量统计,")
    print("以及抽样几个 PDF 的图片清单 / 标题层级 / 原文文本样例。")
    return 0


def cmd_audit(args) -> int:
    from nlnotes.audit import audit
    from nlnotes.scan import select_items
    cfg = _cfg(args)
    items = select_items(cfg, args.ids, args.filter_path, args.limit, include_excluded=True)
    out = audit(cfg, items)
    print(f"\n报告已写入: {cfg.build_dir / 'audit.md'}")
    if out["drop"]:
        print(f"有 {out['drop']} 个 PDF 被剔除,后续阶段会自动跳过。"
              f"处理办法见报告的「必须剔除」一节。")
    return 0


# ------------------------------------------------------------------ 协议级面试复习

def _pick_groups(cfg, args) -> list[dict]:
    from nlnotes.groups import discover_groups
    groups = discover_groups(cfg, args.filter_path)
    if getattr(args, "group", None):
        wanted = [g.lower() for g in args.group]
        picked = [g for g in groups.values()
                  if g["key"].lower() in wanted or g["id"].lower() in wanted
                  or any(w in g["key"].lower() for w in wanted)]
        if not picked:
            raise KeyError(f"找不到分组: {args.group};可用分组: {sorted(groups)}")
        return picked
    return [groups[k] for k in sorted(groups)]


def cmd_groups(args) -> int:
    from nlnotes.groups import build_group_task, chapter_notes
    cfg = _cfg(args)
    picked = _pick_groups(cfg, args)
    if args.list:
        print(f"共 {len(picked)} 个分组(按最后一层目录聚合):\n")
        for g in picked:
            done = len(chapter_notes(cfg, g))
            print(f"- {g['key']}  (id: {g['id']})")
            print(f"    章节: {len(g['items'])} 个,已完成笔记: {done} 个"
                  f"{'  ✅ 可生成面试复习' if done else '  ⚠️ 先完成章节笔记'}")
        return 0
    made = 0
    for g in picked:
        try:
            build_group_task(cfg, g, force=args.force)
            made += 1
        except FileNotFoundError as exc:
            log(str(exc), "warn")
    print(f"\n已生成 {made} 个面试复习任务包(共 {len(picked)} 个分组)")
    return 0


def cmd_build_group(args) -> int:
    from nlnotes.assemble import assemble_group, build_index
    from nlnotes.groups import verify_interview
    from nlnotes.verify import format_report
    cfg = _cfg(args)
    picked = _pick_groups(cfg, args)
    failed = []
    for g in picked:
        rep = verify_interview(cfg, g)
        if not rep.passed:
            print(format_report(rep))
            failed.append(g["key"])
            if not args.force:
                log(f"{g['key']} 未通过校验,跳过生成(如需强制生成加 --force)", "warn")
                continue
        try:
            assemble_group(cfg, g, verified=rep.passed, stats=rep.stats)
        except Exception as exc:
            log(f"组装失败 {g['key']}: {exc}", "error")
            failed.append(g["key"])
    build_index(cfg)
    return 1 if failed else 0


# ------------------------------------------------------------------ AI 自动撰写

def cmd_write(args) -> int:
    import time as _time
    from nlnotes.scan import select_items
    from nlnotes.writer import append_log, summarize, write_chapter
    cfg = _cfg(args)
    items = select_items(cfg, args.ids, args.filter_path, args.limit)
    if not items:
        print("没有待处理的章节。")
        return 0
    print(f"模型: {cfg['writer_model']}  @ {cfg['writer_base_url']}")
    print(f"待处理 {len(items)} 章{'(仅预估,不发请求)' if args.dry_run else ''}\n")

    stats = []
    for i, it in enumerate(items, start=1):
        log(f"[{i}/{len(items)}] {it['rel_path']}")
        try:
            st = write_chapter(cfg, it, dry_run=args.dry_run, force=args.force)
        except Exception as exc:
            log(f"失败 {it['rel_path']}: {exc}", "error")
            st = {"id": it["id"], "rel_path": it["rel_path"], "rounds": 0,
                  "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0,
                  "passed": False, "kind": "chapter", "error": str(exc)}
        stats.append(st)
        if not args.dry_run:
            append_log(cfg, st)
            if i < len(items):
                _time.sleep(float(cfg["writer_sleep_between"]))
    print(summarize(stats, dry_run=args.dry_run))
    if args.dry_run:
        return 0
    return 0 if all(s.get("passed") for s in stats) else 1


def cmd_write_group(args) -> int:
    from nlnotes.writer import append_log, summarize, write_group
    cfg = _cfg(args)
    picked = _pick_groups(cfg, args)
    print(f"模型: {cfg['writer_model']}  @ {cfg['writer_base_url']}")
    print(f"待处理 {len(picked)} 个分组{'(仅预估)' if args.dry_run else ''}\n")
    stats = []
    for i, g in enumerate(picked, start=1):
        log(f"[{i}/{len(picked)}] {g['key']}")
        try:
            st = write_group(cfg, g, dry_run=args.dry_run, force=args.force)
        except Exception as exc:
            log(f"失败 {g['key']}: {exc}", "error")
            st = {"id": g["id"], "rel_path": g["key"], "rounds": 0,
                  "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0,
                  "passed": False, "kind": "group", "error": str(exc)}
        stats.append(st)
        if not args.dry_run:
            append_log(cfg, st)
    print(summarize(stats, dry_run=args.dry_run))
    if args.dry_run:
        return 0
    return 0 if all(s.get("passed") for s in stats) else 1


def cmd_cost(args) -> int:
    """汇总 build/write-log.jsonl 的实际用量与费用。"""
    import json as _json
    cfg = _cfg(args)
    p = cfg.build_dir / "write-log.jsonl"
    if not p.exists():
        print(f"还没有用量记录({p} 不存在)。跑过 nlnotes write 之后才会有。")
        return 0
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(_json.loads(line))
            except Exception:
                pass
    if not rows:
        print("用量记录为空。")
        return 0
    tin = sum(r.get("prompt_tokens", 0) for r in rows)
    tout = sum(r.get("completion_tokens", 0) for r in rows)
    cost = sum(r.get("cost_usd", 0.0) for r in rows)
    ok = sum(1 for r in rows if r.get("passed"))
    by_model: dict[str, float] = {}
    for r in rows:
        by_model[r.get("model", "?")] = by_model.get(r.get("model", "?"), 0.0) + r.get("cost_usd", 0.0)
    print(f"记录条数: {len(rows)}(通过 {ok})")
    print(f"token   : 输入 {tin:,} + 输出 {tout:,}")
    print(f"费用    : 约 ${cost:.2f}")
    print("按模型  :")
    for m, c in sorted(by_model.items(), key=lambda x: -x[1]):
        print(f"  {m}: ${c:.2f}")
    per = [r for r in rows if not r.get("skipped")]
    if per:
        print(f"单章平均: ${cost / len(per):.4f}")
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

    sp = sub.add_parser("audit", help="PDF 体检:能否搜索、是否扫描件,并剔除不可用文件")
    _common(sp)
    _select(sp)
    sp.set_defaults(func=cmd_audit)

    sp = sub.add_parser("diag", help="把调参需要的信息打包成一个文件(build/diagnosis.md)")
    _common(sp)
    sp.add_argument("--sample", type=int, default=3, help="抽样展示几个 PDF 的细节")
    sp.set_defaults(func=cmd_diag)

    sp = sub.add_parser("groups", help="按协议分组,生成面试复习任务包")
    _common(sp)
    sp.add_argument("--group", nargs="*", help="只处理指定分组(支持关键字,如 OSPF)")
    sp.add_argument("--path", dest="filter_path", help="按相对路径关键字筛选")
    sp.add_argument("--list", action="store_true", help="只列出分组与完成情况")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_groups)

    sp = sub.add_parser("build-group", help="校验 + 渲染协议级面试复习笔记")
    _common(sp)
    sp.add_argument("--group", nargs="*", help="只处理指定分组")
    sp.add_argument("--path", dest="filter_path", help="按相对路径关键字筛选")
    sp.add_argument("--force", action="store_true", help="校验不通过也强行生成")
    sp.set_defaults(func=cmd_build_group)

    sp = sub.add_parser("write", help="调 LLM 自动撰写章节 note.json(写→校验→修 闭环)")
    _common(sp)
    _select(sp)
    sp.add_argument("--force", action="store_true", help="已通过校验的章节也重新撰写")
    sp.add_argument("--dry-run", action="store_true", help="只估算 token 与费用,不发请求")
    sp.set_defaults(func=cmd_write)

    sp = sub.add_parser("write-group", help="调 LLM 自动撰写协议级 interview.json")
    _common(sp)
    sp.add_argument("--group", nargs="*")
    sp.add_argument("--path", dest="filter_path")
    sp.add_argument("--limit", type=int)
    sp.add_argument("--force", action="store_true")
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=cmd_write_group)

    sp = sub.add_parser("cost", help="汇总 AI 撰写的实际 token 用量与费用")
    _common(sp)
    sp.set_defaults(func=cmd_cost)

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
