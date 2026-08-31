"""命令行入口:python -m nlnotes <子命令>"""
from __future__ import annotations

import argparse
import json
import os
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
    if cfg.path:
        _missing, _stale = config_diff(cfg.path)
        if _missing or _stale:
            print(f"                ⚠️ 比当前版本少 {len(_missing)} 个配置项"
                  + (f"、多 {len(_stale)} 个废弃项" if _stale else "")
                  + " -> 跑 `python -m nlnotes init --upgrade` 补齐")
            if _missing:
                print(f"                   缺少: {', '.join(_missing[:8])}"
                      + (" ..." if len(_missing) > 8 else ""))
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

    from nlnotes.extract import ocr_status
    st = ocr_status(cfg)
    if not st["enabled"]:
        print(f"\n图内文字 OCR : ➖ 未启用(config 的 figure_ocr = false)")
        print("  -> 拓扑图里的设备名/网段只在图片里。不开 OCR 就要靠 AI 看图登记 labels_seen;")
        print("     子网划分、VLAN 这类图上带大量数值的章节,建议开启")
    elif st["available"]:
        print(f"\n图内文字 OCR : ✅ 可用 — {st['cmd']}")
    else:
        print(f"\n图内文字 OCR : ❌ 已开启但不可用 — {st['reason']}")
        ok = False

    from nlnotes.visuals import find_font
    font = find_font(cfg)
    print(f"\n中文字体      : {font or '❌ 未找到(自制图中文会变方块)'}")
    if not font:
        print("  -> 在 config/pipeline.json 设置 font_path,例如 C:/Windows/Fonts/msyh.ttc")
        ok = False

    if os.name == "nt":
        from nlnotes.util import path_too_long
        try:
            from nlnotes.scan import load_manifest
            longs = [it["rel_path"] for it in load_manifest(cfg)["items"]
                     if path_too_long(it["abs_path"])]
        except Exception:
            longs = []
        if longs:
            print(f"\n长路径      : ⚠️ 有 {len(longs)} 个文件的完整路径超过 Windows 260 字符上限")
            print(f"  例如: {longs[0][:110]}")
            print("  -> 工具内部已用长路径模式处理,但建议同时开启系统长路径支持:")
            print('     以管理员身份运行 PowerShell,执行:')
            print('     New-ItemProperty -Path "HKLM:\\SYSTEM\\CurrentControlSet\\Control\\FileSystem" '
                  '-Name LongPathsEnabled -Value 1 -PropertyType DWORD -Force')
        else:
            print("\n长路径      : ✅ 没有超长路径")

    from nlnotes import selection
    sel_path = selection.selection_path(cfg)
    includes, excludes = selection.load_rules(cfg)
    if includes or excludes:
        print(f"选课清单    : {sel_path}(包含 {len(includes)} 条 / 排除 {len(excludes)} 条)"
              f" -> 用 `select --list` 预览命中情况")
    else:
        print(f"选课清单    : 未启用(处理全部课程)。用 `select --init` 生成清单只做指定方向")

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
    batch = pending[:args.count]

    if args.ids_only:
        for it in batch:
            print(it["id"])
        return 0
    if args.json:
        print(json.dumps({
            "pending_total": len(pending),
            "items": [{"id": it["id"], "title": it["title"],
                       "rel_path": it["rel_path"],
                       "task": str(cfg.task_dir(it["id"]) / "TASK.md"),
                       "output": str(cfg.task_dir(it["id"]) / "OUTPUT" / "note.json")}
                      for it in batch],
        }, ensure_ascii=False, indent=2))
        return 0

    if not pending:
        print("🎉 所有 PDF 都已产出 note.json。")
        print("下一步:build 出笔记,再用 groups / build-group 出面试复习笔记。")
        return 0
    print(f"剩余 {len(pending)} 个待撰写,接下来 {len(batch)} 个:\n")
    for it in batch:
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


def cmd_select(args) -> int:
    from nlnotes import selection
    cfg = _cfg(args)
    if args.init:
        selection.init_file(cfg, force=args.force)
        print(f"\n请编辑 {selection.selection_path(cfg)},取消你想做的方向前面的 #,")
        print("然后用 python -m nlnotes select --list 预览命中情况。")
        return 0
    text = selection.preview(cfg)
    print(text)
    from nlnotes.util import write_text
    out = cfg.build_dir / "selection-preview.md"
    write_text(out, text)
    print(f"预览已写入: {out}")
    return 0


def cmd_dups(args) -> int:
    from nlnotes.dups import report, write_pointers
    cfg = _cfg(args)
    text = report(cfg)
    out = cfg.build_dir / "duplicates.md"
    from nlnotes.util import write_text
    write_text(out, text)
    print(text)
    print(f"报告已写入: {out}")
    if args.write_pointers:
        write_pointers(cfg)
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
        # 先精确匹配:完整分组键 / 分组 id / 末级目录名。
        # --group OSPF 这种写法会命中很多分组,所以只有精确匹配全部落空时才退回模糊匹配,
        # 并且把命中的分组打印出来,避免不知不觉处理了一堆分组。
        picked = [g for g in groups.values()
                  if g["key"].lower() in wanted or g["id"].lower() in wanted
                  or g["title"].lower() in wanted]
        if not picked:
            picked = [g for g in groups.values()
                      if any(w in g["key"].lower() for w in wanted)]
            if len(picked) > 1:
                log(f"“{', '.join(args.group)}”模糊匹配到 {len(picked)} 个分组:"
                    + "、".join(g["key"] for g in picked[:8])
                    + (" ..." if len(picked) > 8 else "")
                    + "。要精确指定请用完整分组键或 id(见 groups --list)", "warn")
        if not picked:
            raise KeyError(f"找不到分组: {args.group};"
                           f"可用分组见 nlnotes groups --list")
        return picked
    return [groups[k] for k in sorted(groups)]


def cmd_groups(args) -> int:
    from nlnotes.groups import build_group_task, chapter_notes
    cfg = _cfg(args)
    picked = _pick_groups(cfg, args)
    if args.list:
        if getattr(args, "json", False):
            import json as _json
            print(_json.dumps([
                {"id": g["id"], "key": g["key"], "title": g["title"],
                 "chapters": len(g["items"]),
                 "notes_done": len(chapter_notes(cfg, g))}
                for g in sorted(picked, key=lambda x: -len(x["items"]))
            ], ensure_ascii=False, indent=2))
            return 0
        mode = str(cfg.get("group_mode", "auto")).lower()
        if mode == "selection":
            how = "按选课清单的每条包含规则分组 —— 一条规则出一份面试复习笔记"
        elif mode == "auto":
            how = f"自适应聚合,每组至少 {cfg['group_min_chapters']} 章"
        elif int(cfg["group_depth"]) > 0:
            how = f"按第 {cfg['group_depth']} 层目录聚合"
        else:
            how = "按最后一层目录聚合"
        print(f"共 {len(picked)} 个分组({how}):\n")
        for g in sorted(picked, key=lambda x: -len(x["items"])):
            done = len(chapter_notes(cfg, g))
            print(f"- {g['key']}  (id: {g['id']})")
            print(f"    章节: {len(g['items'])} 个,已完成笔记: {done} 个"
                  f"{'  ✅ 可生成面试复习' if done else '  ⚠️ 先完成章节笔记'}")
        print(f"\n说明:分组数 = 最终会产出多少份面试复习笔记。")
        if mode == "selection":
            print("      想改分组粒度,直接改选课清单的规则即可。")
        elif mode == "auto":
            print("      切得太碎就调大 group_min_chapters,太粗就调小;")
            print("      想让一个协议只出一份,把 group_mode 改成 selection。")
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
    from nlnotes.writer import append_log, probe, summarize, write_chapter
    cfg = _cfg(args)
    if args.probe:
        return probe(cfg)
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


def cmd_stats(args) -> int:
    """汇总已完成笔记的客观质量指标 —— 用来对比不同模型的产出质量。"""
    from nlnotes.scan import select_items
    cfg = _cfg(args)
    items = select_items(cfg, args.ids, args.filter_path, None)
    rows = []
    for it in items:
        rep = cfg.report_dir() / f"{it['id']}.json"
        if not rep.exists():
            continue
        try:
            r = read_json(rep)
        except Exception:
            continue
        st = r.get("stats") or {}
        if not st:
            continue
        rows.append({"id": it["id"], "title": it["title"], "passed": r.get("passed"),
                     "errors": r.get("error_count", 0), **st})

    if not rows:
        print("还没有校验报告。先跑 verify 或 build。")
        return 0

    def avg(key, default=0.0):
        vals = [x.get(key) for x in rows if isinstance(x.get(key), (int, float))]
        return sum(vals) / len(vals) if vals else default

    passed = sum(1 for x in rows if x["passed"])
    print(f"已校验章节: {len(rows)}  通过 {passed}  未通过 {len(rows) - passed}")
    print()
    print("质量指标(平均值,用来对比不同模型的产出):")
    print(f"  知识点密度      : {avg('points_per_content_page'):.2f} 条/正文页"
          f"   (门槛 {cfg['min_points_per_content_page']})")
    print(f"  每章知识点总数  : {avg('points_total'):.1f}")
    print(f"  填了深入说明的  : {avg('points_with_detail'):.1f} 条/章")
    print(f"  内容覆盖率      : {avg('coverage_ratio') * 100:.1f}%"
          f"   (门槛 {float(cfg['coverage_min_ratio']) * 100:.0f}%)")
    print(f"  引用校验通过率  : "
          f"{avg('quotes_matched') / max(0.01, avg('quotes_checked')) * 100:.1f}%")
    print(f"  每章引用条数    : {avg('quotes_checked'):.1f}")
    print(f"  拓扑图引用      : {avg('figures_used'):.1f} / {avg('figures_available'):.1f} 张")
    print(f"  自制图数量      : {avg('visuals'):.1f} 个/章")
    print(f"  费曼题目数      : {avg('questions'):.1f} 道/章")
    print(f"  无原文依据 token: {avg('ungrounded_tokens'):.2f} 个/章")
    print()
    print("怎么看这些数:密度、覆盖率、自制图数量越高说明笔记越扎实;")
    print("             未通过数与无依据 token 越高说明模型越吃力(会更耗额度)。")

    if args.detail:
        print()
        print(f"{'状态':<6}{'密度':>6}{'覆盖':>7}{'图':>5}{'题':>4}  章节")
        for x in sorted(rows, key=lambda r: r.get("points_per_content_page", 0)):
            print(f"{'✅' if x['passed'] else '❌':<6}"
                  f"{x.get('points_per_content_page', 0):>6.1f}"
                  f"{x.get('coverage_ratio', 0) * 100:>6.0f}%"
                  f"{x.get('figures_used', 0):>5}"
                  f"{x.get('questions', 0):>4}  {x['title'][:50]}")
    return 0


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


def config_diff(path=None) -> tuple[list[str], list[str]]:
    """返回 (配置文件缺少的新增项, 配置文件里已不存在的旧项)。"""
    from nlnotes.config import DEFAULTS
    from nlnotes.util import read_json
    p = path or DEFAULT_CONFIG_PATH
    if not Path(p).exists():
        return [], []
    try:
        user = read_json(p)
    except Exception:
        return [], []
    missing = [k for k in DEFAULTS if k not in user]
    stale = [k for k in user if k not in DEFAULTS]
    return missing, stale


def cmd_init(args) -> int:
    """生成 config/pipeline.json;--upgrade 为已有配置补齐新增项。"""
    from nlnotes.config import DEFAULTS
    from nlnotes.util import read_json, write_json

    example = DEFAULT_CONFIG_PATH.parent / "pipeline.example.json"

    if args.upgrade:
        if not DEFAULT_CONFIG_PATH.exists():
            print(f"{DEFAULT_CONFIG_PATH} 还不存在,请先运行 python -m nlnotes init")
            return 1
        user = read_json(DEFAULT_CONFIG_PATH)
        missing, stale = config_diff()
        if not missing and not stale:
            print(f"配置已是最新,没有需要补齐的项({len(user)} 项)。")
            return 0
        merged = {k: user.get(k, v) for k, v in DEFAULTS.items()}   # 保留你改过的值
        backup = DEFAULT_CONFIG_PATH.with_suffix(".json.bak")
        shutil.copyfile(DEFAULT_CONFIG_PATH, backup)
        write_json(DEFAULT_CONFIG_PATH, merged)
        print(f"已升级 {DEFAULT_CONFIG_PATH}(原文件备份为 {backup.name})")
        if missing:
            print(f"\n补齐了 {len(missing)} 个新增配置项(取默认值):")
            for k in missing:
                print(f"  + {k} = {json.dumps(DEFAULTS[k], ensure_ascii=False)}")
        if stale:
            print(f"\n移除了 {len(stale)} 个已废弃的项:{stale}")
        print("\n你原先改过的值都保留了。各项含义见 config/pipeline.example.json 的注释"
              "与 docs/02-流水线详解.md。")
        return 0

    if DEFAULT_CONFIG_PATH.exists() and not args.force:
        missing, stale = config_diff()
        print(f"{DEFAULT_CONFIG_PATH} 已存在。")
        if missing or stale:
            print(f"\n⚠️ 它比当前版本少 {len(missing)} 个配置项"
                  + (f"、多 {len(stale)} 个已废弃项" if stale else "") + "。")
            if missing:
                print(f"   缺少:{', '.join(missing[:10])}"
                      + (" ..." if len(missing) > 10 else ""))
            print("\n   补齐(会保留你改过的值,并备份原文件):")
            print("     python -m nlnotes init --upgrade")
        else:
            print("配置已是最新。要完全重置请加 --force。")
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

    sp = sub.add_parser("init", help="生成 config/pipeline.json;--upgrade 补齐新增配置项")
    sp.add_argument("--upgrade", action="store_true",
                    help="为已有配置补齐新增项(保留你改过的值,自动备份)")
    sp.add_argument("--force", action="store_true", help="完全重置为默认配置")
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
    sp.add_argument("--json", action="store_true", help="输出机器可读 JSON(便于脚本/AI 消费)")
    sp.add_argument("--ids-only", action="store_true", help="只输出 pdf_id,一行一个")
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

    sp = sub.add_parser("select", help="选课清单:指定只对哪些课程做笔记")
    _common(sp)
    sp.add_argument("--init", action="store_true", help="按课程库生成清单模板")
    sp.add_argument("--list", action="store_true", help="预览清单命中了哪些课程(默认行为)")
    sp.add_argument("--force", action="store_true", help="配合 --init 覆盖已有清单")
    sp.set_defaults(func=cmd_select)

    sp = sub.add_parser("dups", help="重复内容报告:哪些 PDF 内容完全相同,实际要写多少章")
    _common(sp)
    sp.add_argument("--write-pointers", action="store_true",
                    help="为副本生成指向正本笔记的短笔记,保持目录树完整")
    sp.set_defaults(func=cmd_dups)

    sp = sub.add_parser("diag", help="把调参需要的信息打包成一个文件(build/diagnosis.md)")
    _common(sp)
    sp.add_argument("--sample", type=int, default=3, help="抽样展示几个 PDF 的细节")
    sp.set_defaults(func=cmd_diag)

    sp = sub.add_parser("groups", help="按协议分组,生成面试复习任务包")
    _common(sp)
    sp.add_argument("--group", nargs="*", help="只处理指定分组(支持关键字,如 OSPF)")
    sp.add_argument("--path", dest="filter_path", help="按相对路径关键字筛选")
    sp.add_argument("--list", action="store_true", help="只列出分组与完成情况")
    sp.add_argument("--json", action="store_true", help="配合 --list,输出机器可读 JSON")
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
    sp.add_argument("--probe", action="store_true",
                    help="只探测能不能连上模型服务(发一个极短请求),不写笔记")
    sp.set_defaults(func=cmd_write)

    sp = sub.add_parser("write-group", help="调 LLM 自动撰写协议级 interview.json")
    _common(sp)
    sp.add_argument("--group", nargs="*")
    sp.add_argument("--path", dest="filter_path")
    sp.add_argument("--limit", type=int)
    sp.add_argument("--force", action="store_true")
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=cmd_write_group)

    sp = sub.add_parser("stats", help="汇总已完成笔记的质量指标(用来对比不同模型)")
    _common(sp)
    _select(sp)
    sp.add_argument("--detail", action="store_true", help="逐章列出")
    sp.set_defaults(func=cmd_stats)

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
