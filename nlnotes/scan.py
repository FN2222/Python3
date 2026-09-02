"""阶段 1 —— 扫描课程目录树,生成 manifest.json。

支持任意深度嵌套(方向 / 子方向 / 协议 / ... / *.pdf),输出目录树将与源目录树一一镜像。
对源 PDF 只做只读打开与哈希,绝不写回。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from nlnotes.config import Config
from nlnotes.util import (file_sha256, log, path_too_long, pdf_id_for,
                          read_json, slugify, sys_path, write_json)

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
    long_paths: list[str] = []
    for p in pdf_paths:
        rel = p.relative_to(root).as_posix()
        pid = pdf_id_for(rel)
        while pid in seen_ids:          # 理论上不会发生,保险处理
            pid += "x"
        seen_ids.add(pid)

        if path_too_long(p):
            long_paths.append(str(p))
        try:
            stat = os.stat(sys_path(p))
        except OSError as exc:
            log(f"跳过无法读取的文件({exc}): {p}", "warn")
            continue
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

    if long_paths:
        log(f"有 {len(long_paths)} 个文件的路径超过 Windows 的 260 字符上限,"
            f"已用长路径模式处理(例如 {Path(long_paths[0]).name})。"
            f"建议同时开启 Windows 的长路径支持,见 docs/05-常见问题.md", "warn")

    dup_stats = _mark_duplicates(items)

    manifest = {
        "source_root": str(root),
        "notes_dir": str(cfg.notes_dir),
        "count": len(items),
        "categories": sorted({it["course_path"][0] for it in items if it["course_path"]}),
        "duplicates": dup_stats,
        "long_path_count": len(long_paths),
        "items": items,
    }
    write_json(cfg.manifest_path, manifest)
    log(f"扫描完成: {len(items)} 个 PDF,{len(manifest['categories'])} 个一级方向 -> {cfg.manifest_path}", "ok")
    return manifest


def _mark_duplicates(items: list[dict[str, Any]]) -> dict[str, Any]:
    """标记内容完全相同的 PDF(SHA-256 一致)。

    NetworkLessons 会把同一节课交叉归档到多个认证方向(CCNA / CCNP / CCIE /
    Routing & Switching),所以文件总数远大于实际课程数。同一份内容写两遍笔记
    既浪费额度又没意义,所以这里挑一个"正本"(路径排序最靠前的那个),
    其余标记 dup_of 指向它。后续阶段默认跳过副本,并为副本生成指向正本的短笔记。
    """
    by_hash: dict[str, list[dict[str, Any]]] = {}
    for it in items:
        sha = it.get("sha256") or ""
        if not sha:
            continue
        by_hash.setdefault(sha, []).append(it)

    dup_groups = 0
    dup_files = 0
    for sha, group in by_hash.items():
        for it in group:
            it["dup_of"] = None
            it["dup_count"] = len(group)
        if len(group) < 2:
            continue
        dup_groups += 1
        group.sort(key=lambda x: x["rel_path"])
        canonical = group[0]
        for other in group[1:]:
            other["dup_of"] = canonical["id"]
            dup_files += 1

    # ---- 标题层面的近似重复 ----
    # 交叉归档时文件常被重新导出(PDF 元数据/时间戳不同),字节哈希抓不到,
    # 但文件名去掉序号前缀后是同一节课。这类只报告,默认不跳过。
    import re as _re
    by_title: dict[str, list[dict[str, Any]]] = {}
    for it in items:
        key = _re.sub(r"^\s*\d{1,4}\s*[-.)]?\s*", "", it["file_stem"])
        key = _re.sub(r"\s+", " ", key).strip().lower()
        if key:
            by_title.setdefault(key, []).append(it)

    title_groups = 0
    title_dups = 0
    for _key, group in by_title.items():
        for it in group:
            it["title_dup_of"] = None
            it["title_dup_count"] = len(group)
        if len(group) < 2:
            continue
        title_groups += 1
        group.sort(key=lambda x: x["rel_path"])
        for other in group[1:]:
            if not other.get("dup_of"):        # 已被字节哈希判为副本的不重复计
                other["title_dup_of"] = group[0]["id"]
                title_dups += 1

    return {
        "duplicate_groups": dup_groups,
        "duplicate_files": dup_files,
        "unique_files": len(items) - dup_files,
        "title_duplicate_groups": title_groups,
        "title_duplicate_files": title_dups,
        "unique_by_title": len(items) - dup_files - title_dups,
        "largest_title_groups": sorted(
            ({"title": k, "count": len(g),
              "paths": [x["rel_path"] for x in g[:6]]}
             for k, g in by_title.items() if len(g) > 1),
            key=lambda x: -x["count"])[:15],
        "largest_groups": sorted(
            ({"sha256": sha[:12], "count": len(g),
              "canonical": g[0]["rel_path"],
              "others": [x["rel_path"] for x in g[1:6]]}
             for sha, g in by_hash.items() if len(g) > 1),
            key=lambda x: -x["count"])[:15],
    }


def load_manifest(cfg: Config) -> dict[str, Any]:
    if not cfg.manifest_path.exists():
        raise FileNotFoundError(f"未找到 {cfg.manifest_path},请先运行: nlnotes scan")
    return read_json(cfg.manifest_path)


def select_items(cfg: Config, ids: list[str] | None = None,
                 filter_path: str | None = None,
                 limit: int | None = None,
                 include_excluded: bool = False) -> list[dict[str, Any]]:
    """按 id 前缀 / 路径关键字筛选待处理的 PDF,并自动跳过体检剔除的文件。"""
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

    if not ids:
        from nlnotes import selection
        items = selection.apply(cfg, items)

    if cfg.get("respect_audit_exclusions") and not include_excluded and not ids:
        from nlnotes.audit import excluded_ids
        dropped = excluded_ids(cfg)
        if dropped:
            before = len(items)
            items = [it for it in items if it["id"] not in dropped]
            if before != len(items):
                log(f"已跳过体检剔除的 {before - len(items)} 个 PDF"
                    f"(详见 build/audit.md;要强制处理请显式传 --id)")

    if cfg.get("skip_duplicate_content") and not include_excluded and not ids:
        before = len(items)
        items = [it for it in items if not it.get("dup_of")]
        if before != len(items):
            log(f"已跳过内容完全相同的 {before - len(items)} 个副本 PDF"
                f"(同一节课被交叉归档到多个认证方向;详见 nlnotes dups)")

    if cfg.get("skip_title_duplicates") and not include_excluded and not ids:
        before = len(items)
        items = [it for it in items if not it.get("title_dup_of")]
        if before != len(items):
            log(f"已跳过标题重复的 {before - len(items)} 个 PDF"
                f"(字节不同但很可能是同一节课;详见 nlnotes dups)")

    if limit:
        items = items[:limit]
    return items


def get_item(cfg: Config, pdf_id: str) -> dict[str, Any]:
    picked = select_items(cfg, ids=[pdf_id])
    if not picked:
        raise KeyError(f"找不到 id: {pdf_id}")
    return picked[0]
