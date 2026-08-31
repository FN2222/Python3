"""选课清单 —— 指定只对哪些课程做笔记。

课程库有近 2000 个 PDF,而且同一个协议会交叉出现在多个认证方向下,
绝大多数人只需要其中一部分。与其每条命令都写一长串 `--path`,
不如在一个清单文件里把范围定下来,所有命令自动遵守。

清单文件(默认 `config/selection.txt`)的写法:

    # 以 # 开头是注释
    Routing & Switching/OSPF        # 目录名片段:包含即匹配
    Routing & Switching/BGP
    Cisco/CCNP ENCOR*/Unit 2*       # 含 * 或 ? 时按通配符匹配整条相对路径
    !*/Labs/*                       # ! 开头表示排除,排除优先于包含

规则:
  * 只要有一条"包含"规则,就只处理匹配上的;一条都没有则处理全部。
  * "排除"始终优先。
  * 匹配对象是相对课程根目录的路径(统一用 / 分隔),不区分大小写。
"""
from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any

from nlnotes.config import REPO_ROOT, Config
from nlnotes.util import log, write_text

TEMPLATE_HEADER = """# nlnotes 选课清单
#
# 作用:只对下面列出的课程做笔记。所有命令(extract / tasks / write / build 等)
#       都会自动遵守这个清单,不需要每次再写 --path。
#
# 写法:
#   Routing & Switching/OSPF      目录名片段,包含即匹配(不区分大小写)
#   Cisco/CCNP ENCOR*/Unit 2*     含 * 或 ? 时,按通配符匹配整条相对路径
#   !*/Labs/*                     ! 开头表示排除;排除优先于包含
#   # 这一行是注释
#
# 规则:只要有一条包含规则,就只处理匹配上的;全部注释掉则处理全部课程。
#
# 改完用这条命令预览命中了哪些:
#   python -m nlnotes select --list
#
# ---------------------------------------------------------------------------
# 下面按你的课程库自动列出了各一级方向与二级目录,取消注释即可启用。
# 建议先只留一两个方向跑通,再逐步放开。
# ---------------------------------------------------------------------------
"""


def selection_path(cfg: Config) -> Path:
    raw = str(cfg.get("selection_file") or "config/selection.txt").replace("\\", "/")
    p = Path(raw)
    return p if p.is_absolute() else (REPO_ROOT / p)


def load_rules(cfg: Config) -> tuple[list[str], list[str]]:
    """返回 (包含规则, 排除规则)。文件不存在或全是注释时,包含规则为空表示不过滤。"""
    p = selection_path(cfg)
    if not p.exists():
        return [], []
    includes: list[str] = []
    excludes: list[str] = []
    for raw in p.read_text(encoding="utf-8-sig").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("!"):
            pat = line[1:].strip()
            if pat:
                excludes.append(pat)
        else:
            includes.append(line)
    return includes, excludes


def _matches(rel_path: str, pattern: str) -> bool:
    target = rel_path.replace("\\", "/").lower()
    pat = pattern.replace("\\", "/").lower()
    if any(ch in pat for ch in "*?["):
        return fnmatch.fnmatch(target, pat) or fnmatch.fnmatch(target, f"*{pat}*")
    return pat in target


def apply(cfg: Config, items: list[dict[str, Any]],
          quiet: bool = False) -> list[dict[str, Any]]:
    includes, excludes = load_rules(cfg)
    if not includes and not excludes:
        return items

    kept: list[dict[str, Any]] = []
    for it in items:
        rel = it["rel_path"]
        if excludes and any(_matches(rel, p) for p in excludes):
            continue
        if includes and not any(_matches(rel, p) for p in includes):
            continue
        kept.append(it)

    if not quiet and len(kept) != len(items):
        log(f"选课清单生效:{len(items)} → {len(kept)} 个 PDF"
            f"(清单见 {selection_path(cfg)};要临时忽略请显式传 --id)")
    return kept


def init_file(cfg: Config, force: bool = False) -> Path:
    """按实际课程库生成一份带注释的清单模板。"""
    from nlnotes.scan import load_manifest
    p = selection_path(cfg)
    if p.exists() and not force:
        log(f"{p} 已存在(加 --force 覆盖)", "warn")
        return p

    lines = [TEMPLATE_HEADER]
    try:
        items = load_manifest(cfg)["items"]
    except FileNotFoundError:
        lines.append("# (还没跑过 nlnotes scan,无法列出目录。跑完 scan 后加 --force 重新生成)\n")
        write_text(p, "\n".join(lines))
        log(f"已生成清单模板: {p}", "ok")
        return p

    from collections import Counter
    # 一级方向 -> 二级目录 -> 数量
    tree: dict[str, Counter[str]] = {}
    top_counts: Counter[str] = Counter()
    for it in items:
        parts = it["course_path"]
        top = parts[0] if parts else "(根目录)"
        top_counts[top] += 1
        second = parts[1] if len(parts) > 1 else "(直接放在该目录下)"
        tree.setdefault(top, Counter())[second] += 1

    for top, _n in top_counts.most_common():
        lines.append(f"\n# ===== {top}({top_counts[top]} 章)=====")
        lines.append(f"# {top}")
        for second, cnt in tree[top].most_common():
            if second.startswith("("):
                continue
            lines.append(f"#   {top}/{second}    # {cnt} 章")
    lines.append("\n# 常见排除项(取消注释即生效)")
    lines.append("# !*/Labs/*")
    lines.append("# !*/Python/*")
    write_text(p, "\n".join(lines) + "\n")
    log(f"已生成清单模板: {p}(按需取消注释)", "ok")
    return p


def preview(cfg: Config) -> str:
    from nlnotes.scan import load_manifest
    includes, excludes = load_rules(cfg)
    items = load_manifest(cfg)["items"]
    kept = apply(cfg, items, quiet=True)

    lines = ["# 选课清单预览", "",
             f"- 清单文件:`{selection_path(cfg)}`"
             + ("" if selection_path(cfg).exists() else "(**不存在** —— 当前处理全部课程)"),
             f"- 包含规则:{len(includes)} 条" + (f" → {includes}" if includes else "(无,处理全部)"),
             f"- 排除规则:{len(excludes)} 条" + (f" → {excludes}" if excludes else ""),
             "",
             f"- 课程库总数:**{len(items)}**",
             f"- 清单命中:**{len(kept)}**",
             ""]
    if not kept:
        lines += ["> ⚠️ 一个都没命中。检查规则里的目录名是否和实际路径一致"
                  "(可以只写片段,如 `OSPF`)。", ""]
        return "\n".join(lines)

    from collections import Counter
    by_cat: Counter[str] = Counter()
    for it in kept:
        by_cat[it["course_path"][0] if it["course_path"] else "(根目录)"] += 1
    lines += ["**命中的分布**", "", "| 一级方向 | 章节数 |", "| --- | --- |"]
    for cat, n in by_cat.most_common():
        lines.append(f"| {cat} | {n} |")
    lines += ["", "**命中的前 15 个文件**", ""]
    for it in kept[:15]:
        lines.append(f"- `{it['rel_path']}`")
    if len(kept) > 15:
        lines.append(f"- ...(还有 {len(kept) - 15} 个)")
    lines.append("")
    return "\n".join(lines)
