"""重复内容处理。

NetworkLessons 会把同一节课交叉归档到多个认证方向(CCNA / CCNP / CCIE /
Routing & Switching / Network Fundamentals),所以 PDF 文件数远大于实际课程数。
同一份内容写两遍中文笔记既浪费额度又没意义。

做法:
  * scan 阶段按 SHA-256 找出内容完全相同的文件,挑路径排序最靠前的作为"正本",
    其余标记 dup_of。
  * 后续阶段默认只处理正本(config 的 skip_duplicate_content)。
  * 本模块负责:出报告,以及为副本生成"指向正本"的短笔记,
    这样 notes/ 的目录树仍与源课程目录完整对应,不会出现空洞。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from nlnotes.config import Config
from nlnotes.scan import load_manifest
from nlnotes.util import ensure_dir, log, rel_posix, write_text

POINTER_TEMPLATE = """---
title: "{title}"
source_pdf: "{rel_path}"
duplicate_of: "{canonical_rel}"
kind: "duplicate-pointer"
generator: "nlnotes"
---

# {title}

> 🔁 **这一节课与另一处的内容完全相同**(PDF 文件的 SHA-256 一致),
> 只是被同时归档到了不同的认证方向下。为避免重复劳动,笔记只写了一份。

**请阅读正本笔记:** [{canonical_title}]({canonical_link})

| | |
| --- | --- |
| 本文件 | `{rel_path}` |
| 正本文件 | `{canonical_rel}` |

<sub>此页由 `nlnotes dups --write-pointers` 自动生成,不含任何课程内容。</sub>
"""


def collect(cfg: Config) -> dict[str, Any]:
    manifest = load_manifest(cfg)
    items = manifest["items"]
    by_id = {it["id"]: it for it in items}
    dups = [it for it in items if it.get("dup_of")]
    groups: dict[str, list[dict[str, Any]]] = {}
    for it in dups:
        groups.setdefault(it["dup_of"], []).append(it)
    return {"manifest": manifest, "items": items, "by_id": by_id,
            "duplicates": dups, "groups": groups,
            "stats": manifest.get("duplicates") or {}}


def report(cfg: Config) -> str:
    data = collect(cfg)
    st = data["stats"]
    total = len(data["items"])
    dup_files = st.get("duplicate_files", 0)
    unique = st.get("unique_files", total)

    lines = ["# 重复内容报告", "",
             f"- PDF 文件总数:**{total}**",
             f"- 内容互不相同的课程数:**{unique}**",
             f"- 重复副本数:**{dup_files}**"
             + (f"({dup_files / total:.0%})" if total else ""),
             f"- 涉及的重复组数:{st.get('duplicate_groups', 0)}", ""]

    if not dup_files:
        lines += ["没有发现内容完全相同的 PDF。", ""]
        return "\n".join(lines)

    lines += ["> 只有正本会被写笔记,副本会生成一篇指向正本的短笔记占位,",
              "> 所以 `notes/` 的目录树仍与源课程目录完整对应。", "",
              "## 重复最多的几组", "",
              "| 份数 | 正本 | 其他位置(最多列 5 个) |", "| --- | --- | --- |"]
    for g in st.get("largest_groups", []):
        others = "<br>".join(f"`{x}`" for x in g.get("others", []))
        lines.append(f"| {g['count']} | `{g['canonical']}` | {others} |")

    lines += ["", "## 按一级方向统计副本数", ""]
    from collections import Counter
    by_cat: Counter[str] = Counter()
    for it in data["duplicates"]:
        by_cat[it["course_path"][0] if it["course_path"] else "(根目录)"] += 1
    lines += ["| 一级方向 | 副本数 |", "| --- | --- |"]
    for cat, n in by_cat.most_common():
        lines.append(f"| {cat} | {n} |")
    lines += ["", f"**结论:实际需要撰写的章节数是 {unique},而不是 {total}。**",
              f"按这个数量估算成本与工期。", ""]
    return "\n".join(lines)


def write_pointers(cfg: Config) -> int:
    """为每个副本生成"指向正本"的短笔记。正本笔记还不存在时跳过。"""
    data = collect(cfg)
    by_id = data["by_id"]
    written = 0
    skipped = 0
    for it in data["duplicates"]:
        canonical = by_id.get(it["dup_of"])
        if not canonical:
            continue
        canonical_md = cfg.notes_dir / canonical["note_rel_path"]
        if not canonical_md.exists():
            skipped += 1
            continue
        md_path = cfg.notes_dir / it["note_rel_path"]
        ensure_dir(md_path.parent)
        write_text(md_path, POINTER_TEMPLATE.format(
            title=it["title"],
            rel_path=it["rel_path"],
            canonical_rel=canonical["rel_path"],
            canonical_title=canonical["title"],
            canonical_link=rel_posix(canonical_md, md_path.parent),
        ))
        written += 1
    log(f"已为 {written} 个副本生成指向正本的笔记"
        + (f";另有 {skipped} 个的正本笔记还没写,稍后重跑即可" if skipped else ""),
        "ok")
    return written
