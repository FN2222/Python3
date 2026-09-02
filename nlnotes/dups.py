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

    lines = ["# 重复内容报告", ""]

    if not st:
        lines += ["> ⚠️ **当前的 manifest 是旧版本生成的,不含重复信息。**",
                  "> 请先重新扫描,再看这份报告:",
                  ">",
                  "> ```",
                  "> python -m nlnotes scan",
                  "> ```", ""]
        return "\n".join(lines)

    tdup = st.get("title_duplicate_files", 0)
    lines += [f"- PDF 文件总数:**{total}**", "",
              "## 一、内容完全相同(SHA-256 一致)", "",
              f"- 重复副本数:**{dup_files}**"
              + (f"({dup_files / total:.0%})" if total else ""),
              f"- 涉及的重复组数:{st.get('duplicate_groups', 0)}",
              f"- 扣掉副本后的课程数:**{unique}**", ""]

    if not dup_files:
        lines += ["没有发现字节完全相同的 PDF。",
                  "",
                  "> 这**不代表没有重复**。交叉归档时文件常被重新导出",
                  "> (PDF 元数据、时间戳不同),字节哈希抓不到,但内容是同一节课。",
                  "> 看下面的第二节。", ""]

    else:
        lines += ["> 只有正本会被写笔记,副本会生成一篇指向正本的短笔记占位,",
                  "> 所以 `notes/` 的目录树仍与源课程目录完整对应。", "",
                  "重复最多的几组:", "",
                  "| 份数 | 正本 | 其他位置(最多列 5 个) |", "| --- | --- | --- |"]
        for g in st.get("largest_groups", []):
            others = "<br>".join(f"`{x}`" for x in g.get("others", []))
            lines.append(f"| {g['count']} | `{g['canonical']}` | {others} |")
        lines.append("")

    # ---------------- 标题层面的近似重复 ----------------
    lines += ["## 二、标题相同(很可能是同一节课被重新导出)", "",
              f"- 标题重复的文件数:**{tdup}**"
              + (f"({tdup / total:.0%})" if total else ""),
              f"- 涉及的标题组数:{st.get('title_duplicate_groups', 0)}",
              f"- 两种重复都扣掉后的课程数:**{st.get('unique_by_title', unique)}**", ""]
    if tdup:
        lines += ["> 这类默认**只报告、不跳过**(标题相同也可能是不同版本的课程)。",
                  "> 确认确实重复后,把 config 的 `skip_title_duplicates` 设为 `true`,",
                  "> 后续阶段就会只处理每组的第一个。", "",
                  "标题重复最多的几组:", "",
                  "| 份数 | 标题 | 出现位置(最多列 6 个) |", "| --- | --- | --- |"]
        for g in st.get("largest_title_groups", []):
            paths = "<br>".join(f"`{x}`" for x in g.get("paths", []))
            lines.append(f"| {g['count']} | {g['title'][:60]} | {paths} |")
        lines.append("")
    else:
        lines += ["没有发现标题重复的 PDF。", ""]

    # ---------------- 结论 ----------------
    real = st.get("unique_by_title", unique)
    lines += ["## 三、结论", "",
              f"- 只扣字节完全相同的:需要撰写 **{unique}** 章",
              f"- 连标题重复也扣掉:需要撰写 **{real}** 章",
              "",
              f"估算成本与工期时用这两个数,不要用文件总数 {total}。", "",
              "> 想进一步缩小范围,用**选课清单**只挑你要的方向:", "",
              "> ```",
              "> python -m nlnotes select --init     # 按课程库生成模板",
              "> python -m nlnotes select --list     # 预览命中情况",
              "> ```", ""]
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
