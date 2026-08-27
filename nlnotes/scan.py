"""阶段 1 —— 扫描课程目录树,生成 manifest.json。

支持任意深度嵌套(方向 / 子方向 / 协议 / ... / *.pdf),输出目录树将与源目录树一一镜像。
对源 PDF 只做只读打开与哈希,绝不写回。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from nlnotes.config import Config
from nlnotes.util import (file_sha256, log, pdf_id_for, read_json, slugify,
                          write_json)

SKIP_DIR_NAMES = {".git", "__pycache__", ".idea", ".vscode", "$RECYCLE.BIN",
                  "System Volume Information", ".Trash", "node_modules"}


def _clean_title(stem: str) -> str:
    """把文件名清理成可读标题: 去掉序号前缀、下划线、多余空白。"""
    import re
    t = stem.replace("_", " ").replace("-", " ")
    t = re.sub(r"^\s*\d{1,3}[\.\)\s]+", "", t)     # "03. Xxx" -> "Xxx"
    t = re.sub(r"\s+", " ", t).strip()
    return t or stem


def scan(cfg: Config, force: bool = False) -> dict[str, Any]:
    root = cfg.source_root
    if not root.exists():
        raise FileNotFoundError(
            f"课程根目录不存在: {root}\n"
            f"请修改 config/pipeline.json 的 source_root,"
            f"或用 --source-root 传入(Windows 路径请写成 D:/NetworkLessons/All-Courses-v3.0)"
        )

    previous: dict[str, Any] = {}
    if cfg.manifest_path.exists() and not force:
        try:
            previous = {it["id"]: it for it in read_json(cfg.manifest_path)["items"]}
        except Exception:
            previous = {}

    items: list[dict[str, Any]] = []
    pdf_paths: list[Path] = []
    for p in sorted(root.rglob("*")):
        if p.is_dir():
            continue
        if p.suffix.lower() != ".pdf":
            continue
        if any(part in SKIP_DIR_NAMES for part in p.relative_to(root).parts):
            continue
        if p.name.startswith("~$") or p.name.startswith("."):
            continue
        pdf_paths.append(p)

    seen_ids: set[str] = set()
    for p in pdf_paths:
        rel = p.relative_to(root).as_posix()
        pid = pdf_id_for(rel)
        while pid in seen_ids:          # 理论上不会发生,保险处理
            pid += "x"
        seen_ids.add(pid)

        stat = p.stat()
        prev = previous.get(pid)
        if prev and prev.get("size") == stat.st_size and abs(prev.get("mtime", 0) - stat.st_mtime) < 1:
            sha = prev.get("sha256", "")     # 大小与时间都没变,复用哈希省时间
        else:
            sha = file_sha256(p)

        course_path = list(p.relative_to(root).parts[:-1])
        items.append({
            "id": pid,
            "rel_path": rel,
            "abs_path": str(p),
            "title": _clean_title(p.stem),
            "file_stem": p.stem,
            "course_path": course_path,
            "course_path_display": " / ".join(course_path) if course_path else "(根目录)",
            "depth": len(course_path),
            "size": stat.st_size,
            "mtime": stat.st_mtime,
            "sha256": sha,
            # 输出位置(镜像源目录树)
            "note_rel_path": (Path(*course_path) / f"{slugify(p.stem, 80)}.md").as_posix()
            if course_path else f"{slugify(p.stem, 80)}.md",
        })

    manifest = {
        "source_root": str(root),
        "notes_dir": str(cfg.notes_dir),
        "count": len(items),
        "categories": sorted({it["course_path"][0] for it in items if it["course_path"]}),
        "items": items,
    }
    write_json(cfg.manifest_path, manifest)
    log(f"扫描完成: {len(items)} 个 PDF,{len(manifest['categories'])} 个一级方向 -> {cfg.manifest_path}", "ok")
    return manifest


def load_manifest(cfg: Config) -> dict[str, Any]:
    if not cfg.manifest_path.exists():
        raise FileNotFoundError(f"未找到 {cfg.manifest_path},请先运行: nlnotes scan")
    return read_json(cfg.manifest_path)


def select_items(cfg: Config, ids: list[str] | None = None,
                 filter_path: str | None = None,
                 limit: int | None = None) -> list[dict[str, Any]]:
    """按 id 前缀 / 路径关键字筛选待处理的 PDF。"""
    items = load_manifest(cfg)["items"]
    if ids:
        wanted = set(ids)
        picked: list[dict[str, Any]] = []
        for it in items:
            if it["id"] in wanted or any(it["id"].startswith(w) for w in wanted):
                picked.append(it)
        missing = [w for w in wanted
                   if not any(it["id"] == w or it["id"].startswith(w) for it in items)]
        if missing:
            raise KeyError(f"manifest 中找不到这些 id: {missing}")
        items = picked
    if filter_path:
        key = filter_path.replace("\\", "/").lower()
        items = [it for it in items if key in it["rel_path"].lower()]
    if limit:
        items = items[:limit]
    return items


def get_item(cfg: Config, pdf_id: str) -> dict[str, Any]:
    picked = select_items(cfg, ids=[pdf_id])
    if not picked:
        raise KeyError(f"找不到 id: {pdf_id}")
    return picked[0]
