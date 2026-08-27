"""阶段 6 —— 组装最终中文笔记 Markdown。

把 note.json + 抽取出的原文配图 + 渲染好的自制图,拼成一份 Markdown,
输出到 notes/ 下与源课程目录**一一镜像**的位置,并把图片复制到同级 assets/ 目录,
使用相对路径引用 —— Obsidian / Typora / VS Code / GitHub 都能直接看图。
"""
from __future__ import annotations

import datetime as _dt
import shutil
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from nlnotes import __version__
from nlnotes.config import REPO_ROOT, Config
from nlnotes.evidence import SourceIndex
from nlnotes.util import ensure_dir, log, read_json, rel_posix, write_text
from nlnotes.visuals import render_all

TEMPLATE_DIR = REPO_ROOT / "templates"

TYPE_LABEL = {
    "concept": "概念", "process": "过程", "compare": "对比",
    "config": "配置", "troubleshoot": "排障", "calculation": "计算",
}


def _pages_fmt(pages: Any) -> str:
    try:
        nums = sorted({int(p) for p in pages})
    except Exception:
        return str(pages)
    return "p." + ", p.".join(str(n) for n in nums) if nums else "-"


def _codes(items: Any) -> str:
    return " · ".join(f"`{x}`" for x in (items or []))


def _env() -> Environment:
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)),
                      undefined=StrictUndefined,
                      trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True)
    env.filters["pages_fmt"] = _pages_fmt
    env.filters["codes"] = _codes
    return env


def _term_table(note: dict[str, Any]) -> tuple[str, str, list[str]]:
    """术语表在 Python 里拼好,避免模板空白控制影响 Markdown 表格。"""
    with_note = any((t.get("note_zh") or "").strip() for t in note.get("terms", []) or [])
    cols = ["英文", "中文", "原文页"] + (["备注"] if with_note else [])
    header = "| " + " | ".join(cols) + " |"
    divider = "| " + " | ".join("---" for _ in cols) + " |"
    rows = []
    for t in note.get("terms", []) or []:
        cells = [str(t.get("en", "")), str(t.get("zh", "")), f"p.{t.get('page', '')}"]
        if with_note:
            cells.append(str(t.get("note_zh") or ""))
        rows.append("| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |")
    return header, divider, rows


def _normalize(note: dict[str, Any]) -> dict[str, Any]:
    """补齐 schema 中的可选字段,使模板可以在 StrictUndefined 下安全渲染。"""
    note.setdefault("prerequisites_zh", [])
    note.setdefault("terms", [])
    for sec in note.get("sections", []):
        sec.setdefault("intro_zh", "")
        for key in ("figures", "visuals", "configs", "tables"):
            sec.setdefault(key, [])
        for pt in sec["points"]:
            pt.setdefault("kind", "fact")
        for fig in sec["figures"]:
            fig.setdefault("callouts_zh", [])
            fig.setdefault("labels_seen", [])
        for v in sec["visuals"]:
            v.setdefault("caption_zh", "")
            v.setdefault("spec", {})
        for cb in sec["configs"]:
            cb.setdefault("lang", "text")
            cb.setdefault("annotations_zh", [])
    fey = note.setdefault("feynman", {})
    fey.setdefault("blind_spots_zh", [])
    fey.setdefault("review_plan_zh", [])
    for q in fey.get("questions", []):
        q.setdefault("figure_refs", [])
        q.setdefault("scoring_points_zh", [])
    return note


def _collect_figure_assets(note: dict[str, Any], index: SourceIndex,
                           extract_dir: Path, assets_dir: Path,
                           note_dir: Path) -> dict[str, dict[str, Any]]:
    by_id = {f["figure_id"]: f for f in index.figures}
    out: dict[str, dict[str, Any]] = {}
    for sec in note.get("sections", []):
        for fig in sec.get("figures", []) or []:
            fid = fig.get("figure_id")
            meta = by_id.get(fid)
            if not meta:
                # 正常情况下 verify 的 G001 会先拦住;这里兜底,避免 assemble 直接崩
                log(f"figure_id 不存在,已跳过: {fid}", "warn")
                out[fid] = {"path": "", "page": "?", "file": ""}
                continue
            src = extract_dir / "figures" / meta["file"]
            dst = assets_dir / meta["file"]
            if src.exists():
                ensure_dir(assets_dir)
                shutil.copyfile(src, dst)
            out[fid] = {"path": rel_posix(dst, note_dir), "page": meta["page"],
                        "file": meta["file"]}
    return out


def _collect_visual_assets(note: dict[str, Any], rendered: dict[str, dict[str, Any]],
                           assets_dir: Path, note_dir: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for sec in note.get("sections", []):
        for v in sec.get("visuals", []) or []:
            res = rendered.get(v["id"], {})
            entry: dict[str, Any] = {"animation": None, "still": None, "video": None,
                                     "inline": None, "lang": "text", "table_md": None,
                                     "unavailable": None}
            if not res.get("ok"):
                entry["unavailable"] = res.get("reason", "未知原因")
                out[v["id"]] = entry
                continue
            if res.get("skipped"):
                entry["unavailable"] = res.get("note", "已跳过")
            for key in ("animation", "still", "video"):
                src = res.get(key)
                if isinstance(src, Path) and src.exists():
                    ensure_dir(assets_dir)
                    dst = assets_dir / src.name
                    shutil.copyfile(src, dst)
                    entry[key] = rel_posix(dst, note_dir)
            if res.get("inline"):
                entry["inline"] = res["inline"]
                entry["lang"] = res.get("lang", "text")
            if res.get("table_md"):
                entry["table_md"] = res["table_md"]
            if any(entry[k] for k in ("animation", "still", "video", "inline", "table_md")):
                entry["unavailable"] = None
            out[v["id"]] = entry
    return out


def assemble_one(cfg: Config, item: dict[str, Any], verified: bool = False,
                 stats: dict[str, Any] | None = None) -> Path:
    from nlnotes.taskgen import note_path

    pdf_id = item["id"]
    np_ = note_path(cfg, pdf_id)
    if not np_.exists():
        raise FileNotFoundError(f"缺少 note.json: {np_}(请先按 TASK.md 产出)")
    note = _normalize(read_json(np_))
    index = SourceIndex.load(cfg.extract_dir(pdf_id))

    md_path = cfg.notes_dir / item["note_rel_path"]
    note_dir = ensure_dir(md_path.parent)
    assets_dir = note_dir / cfg["assets_dirname"] / pdf_id
    if assets_dir.exists():
        shutil.rmtree(assets_dir)

    rendered = render_all(cfg, note, cfg.visual_dir(pdf_id))
    figure_assets = _collect_figure_assets(note, index, cfg.extract_dir(pdf_id),
                                           assets_dir, note_dir)
    visual_assets = _collect_visual_assets(note, rendered, assets_dir, note_dir)

    st = stats or {}
    meta = {
        "version": __version__,
        "generated_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "pages_total": index.pages_total,
        "figures_available": len(index.figure_ids),
        "figures_used": len(figure_assets),
        "visuals": len(visual_assets),
        "coverage": f"{float(st.get('coverage_ratio', 0)) * 100:.0f}%" if st else "未校验",
        "verified": verified,
        "quotes_checked": st.get("quotes_checked", 0),
        "quotes_matched": st.get("quotes_matched", 0),
        "has_ai_illustration": any(
            v.get("kind") == "ai_illustration"
            for sec in note.get("sections", []) for v in sec.get("visuals", []) or []),
    }

    term_header, term_divider, term_rows = _term_table(note)
    tpl = _env().get_template("note.md.j2")
    markdown = tpl.render(
        note=note, meta=meta,
        figure_assets=figure_assets, visual_assets=visual_assets,
        type_label=TYPE_LABEL,
        term_header=term_header, term_divider=term_divider, term_rows=term_rows,
    )
    write_text(md_path, markdown)
    log(f"笔记已生成: {md_path}", "ok")
    return md_path


# ------------------------------------------------------------------ 全局索引

def build_index(cfg: Config) -> Path:
    """生成 notes/README.md:按课程目录树列出所有笔记及其完成状态。"""
    from nlnotes.scan import load_manifest
    from nlnotes.taskgen import note_path

    manifest = load_manifest(cfg)
    items = manifest["items"]
    done = 0
    tree: dict[str, list[dict[str, Any]]] = {}
    for it in items:
        key = it["course_path_display"]
        tree.setdefault(key, []).append(it)

    lines = ["# NetworkLessons 中文笔记索引", "",
             f"- 源课程目录:`{manifest['source_root']}`(只读)",
             f"- 课程文件总数:{len(items)}", ""]
    body: list[str] = []
    for key in sorted(tree):
        body += [f"## {key}", "", "| 状态 | 笔记 | 原文 | 页数 | 图 |", "| --- | --- | --- | --- | --- |"]
        for it in sorted(tree[key], key=lambda x: x["rel_path"]):
            md = cfg.notes_dir / it["note_rel_path"]
            report = cfg.report_dir() / f"{it['id']}.json"
            extract_meta = cfg.extract_dir(it["id"]) / "extract.json"
            pages = figs = "-"
            if extract_meta.exists():
                em = read_json(extract_meta)
                pages, figs = em.get("pages_total", "-"), em.get("figure_count", "-")
            if md.exists():
                passed = report.exists() and read_json(report).get("passed")
                status = "✅ 已校验" if passed else "🟡 待修正"
                done += 1
                link = f"[{it['title']}]({rel_posix(md, cfg.notes_dir)})"
            elif note_path(cfg, it["id"]).exists():
                status, link = "🟠 待组装", it["title"]
            elif (cfg.task_dir(it["id"]) / "TASK.md").exists():
                status, link = "🔵 待撰写", it["title"]
            else:
                status, link = "⚪ 未开始", it["title"]
            body.append(f"| {status} | {link} | `{it['rel_path']}` | {pages} | {figs} |")
        body.append("")

    lines.insert(3, f"- 已生成笔记:{done} / {len(items)}")
    out = cfg.notes_dir / "README.md"
    write_text(out, "\n".join(lines + body))
    log(f"索引已更新: {out}", "ok")
    return out
