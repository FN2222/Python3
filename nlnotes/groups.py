"""协议级面试复习笔记 —— 按目录把多章聚合成一份"面试复习笔记"。

为什么要分组:面试题(基础/原理题、场景题、连环追问、避坑)放在单章后面素材太少,
放在整个协议(整个 OSPF / 整个 BGP)后面才能跨章串联、追问才有深度。

分组键 = 课程相对路径的前 N 层目录(N = config.group_depth,默认取"最后一层目录")。
例如 `IGP/OSPF/xxx.pdf` 与 `IGP/OSPF/yyy.pdf` 会归到同一组 `IGP/OSPF`。

产物:
    build/groups/<group_id>/TASK.md + context.json + chapters.md + interview.schema.json
    build/groups/<group_id>/OUTPUT/interview.json      ← AI 写这里
    notes/<group_key>/00-面试复习-<协议>.md             ← 渲染结果
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from nlnotes.config import REPO_ROOT, Config
from nlnotes.evidence import SourceIndex
from nlnotes.scan import load_manifest
from nlnotes.util import (ensure_dir, log, norm_space, read_json, slugify,
                          write_json, write_text)

SCHEMA_PATH = REPO_ROOT / "schemas" / "interview.schema.json"


# ------------------------------------------------------------------ 分组

ROOT_KEY = "(根目录)"


def group_key_of(item: dict[str, Any], depth: int) -> str:
    """depth 模式:depth<=0 表示取"最后一层目录"(通常就是协议名)。"""
    parts = item["course_path"]
    if not parts:
        return ROOT_KEY
    if depth <= 0:
        return "/".join(parts)
    return "/".join(parts[:depth])


def group_id_of(group_key: str) -> str:
    """路径可能很长,截断后带哈希后缀,保证既可读又唯一。"""
    from nlnotes.util import short_hash
    return f"{slugify(group_key.replace('/', '-'), 50)}-{short_hash(group_key, 6)}"


def _auto_keys(items: list[dict[str, Any]], min_chapters: int) -> dict[str, str]:
    """自适应分组:为每个 PDF 选"章节数达标的最深祖先目录"。

    课程库的目录深度不一(1~6 层),固定层级要么切太碎、要么并太粗。
    做法是先统计每个祖先目录前缀下有多少章,再为每个 PDF 自底向上找第一个
    章节数 >= min_chapters 的前缀。找不到就退回一级目录(允许小分组存在)。
    """
    from collections import Counter
    counts: Counter[str] = Counter()
    for it in items:
        parts = it["course_path"]
        if not parts:
            counts[ROOT_KEY] += 1
            continue
        for d in range(1, len(parts) + 1):
            counts["/".join(parts[:d])] += 1

    assigned: dict[str, str] = {}
    for it in items:
        parts = it["course_path"]
        if not parts:
            assigned[it["id"]] = ROOT_KEY
            continue
        chosen = None
        for d in range(len(parts), 0, -1):
            key = "/".join(parts[:d])
            if counts[key] >= min_chapters:
                chosen = key
                break
        assigned[it["id"]] = chosen or "/".join(parts[:1])
    return assigned


def discover_groups(cfg: Config, filter_path: str | None = None) -> dict[str, dict[str, Any]]:
    """返回 {group_key: {id, key, title, items[]}}。"""
    items = [it for it in load_manifest(cfg)["items"]
             if not filter_path
             or filter_path.replace("\\", "/").lower() in it["rel_path"].lower()]

    mode = str(cfg.get("group_mode", "auto")).lower()
    if mode == "auto":
        # 自适应分组要基于**全库**统计,否则 --path 过滤会让分组边界随筛选条件漂移
        all_items = load_manifest(cfg)["items"]
        keys = _auto_keys(all_items, int(cfg["group_min_chapters"]))
        key_of = lambda it: keys.get(it["id"]) or ROOT_KEY  # noqa: E731
    else:
        depth = int(cfg["group_depth"])
        key_of = lambda it: group_key_of(it, depth)  # noqa: E731

    groups: dict[str, dict[str, Any]] = {}
    for it in items:
        key = key_of(it)
        g = groups.setdefault(key, {
            "id": group_id_of(key), "key": key,
            "title": key.split("/")[-1], "items": [],
        })
        g["items"].append(it)
    for g in groups.values():
        g["items"].sort(key=lambda x: x["rel_path"])
    return groups


def group_dir(cfg: Config, group_id: str) -> Path:
    return cfg.build_dir / "groups" / group_id


def interview_path(cfg: Config, group_id: str) -> Path:
    return group_dir(cfg, group_id) / "OUTPUT" / "interview.json"


def chapter_notes(cfg: Config, group: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """取出本组中"已产出 note.json"的章节 -> [(manifest_item, note)]。"""
    from nlnotes.taskgen import note_path
    out = []
    for it in group["items"]:
        p = note_path(cfg, it["id"])
        if p.exists():
            try:
                out.append((it, read_json(p)))
            except Exception as exc:
                log(f"跳过无法解析的 note.json {it['rel_path']}: {exc}", "warn")
    return out


# ------------------------------------------------------------------ 任务包

def _chapters_md(pairs: list[tuple[dict[str, Any], dict[str, Any]]],
                 budget_chars: int = 90000) -> str:
    """把本组各章笔记的骨架汇总给 AI,作为出题素材(带 pdf_id 与页码,便于填 grounding)。

    分组很大时(几十章)全量骨架会让提示词爆掉,所以按章均摊一个字符预算,
    超出的章节只保留小节标题与"必须掌握 / 难点",并注明完整内容在哪。
    """
    per_chapter = max(1500, budget_chars // max(1, len(pairs)))
    lines = ["# 本协议已完成章节的知识骨架", "",
             "出题只能基于下面这些内容。每条都标了 `pdf_id` 与页码,",
             "填 `grounding` 时直接用这些页码,并回到对应章节的原文复制英文句子。", ""]
    if len(pairs) > 12:
        lines += [f"> 本组共 {len(pairs)} 章,内容较多。为控制篇幅,单章骨架超过约 "
                  f"{per_chapter} 字符时会被截断,",
                  "> 截断处会注明完整内容的位置(`build/tasks/<pdf_id>/OUTPUT/note.json`),"
                  "需要时可自行打开查看。", ""]
    for it, note in pairs:
        start = len(lines)
        lines += [f"## {note.get('title_zh', it['title'])} ({note.get('title_en', '')})", "",
                  f"- `pdf_id`: `{it['id']}`",
                  f"- 源文件: `{it['rel_path']}`",
                  f"- 原文页数: {note.get('meta', {}).get('pages_total', '?')}",
                  f"- 本章边界: {note.get('scope_zh', '')}", "",
                  f"**概要**:{note.get('summary_zh', '')}", ""]

        lines.append("**小节与知识点**")
        lines.append("")
        used = sum(len(x) for x in lines[start:])
        truncated = False
        for sec in note.get("sections", []):
            pages = ", ".join(f"p.{p}" for p in sec.get("pages", []))
            head = f"- **{sec.get('heading_zh')}** ({sec.get('heading_en')}) — {pages}"
            lines.append(head)
            used += len(head)
            if used > per_chapter:
                truncated = True
                continue          # 预算用完后只保留小节标题,不再展开知识点
            for pt in sec.get("points", []):
                row = f"  - (p.{pt.get('page')}) {norm_space(pt.get('text_zh', ''))}"
                quote = f"    - 原文: {norm_space(pt.get('text_en_quote', ''))}"
                lines += [row, quote]
                used += len(row) + len(quote)
                if used > per_chapter:
                    truncated = True
                    break
            for cb in sec.get("configs", []) or []:
                first = norm_space((cb.get("code") or "").splitlines()[0] if cb.get("code") else "")
                row = f"  - (p.{cb.get('page')}) [配置] {first}"
                lines.append(row)
                used += len(row)
        if truncated:
            lines += ["", f"> ⚠️ 本章骨架已按篇幅预算截断。完整内容见 "
                      f"`build/tasks/{it['id']}/OUTPUT/note.json`,"
                      f"原文见 `build/extract/{it['id']}/text.md`。"]
        lines.append("")

        fey = note.get("feynman", {}) or {}
        if fey.get("must_master"):
            lines.append("**本章标注的必须掌握**")
            lines.append("")
            for m in fey["must_master"]:
                pg = ", ".join(f"p.{p}" for p in m.get("source_pages", []))
                lines.append(f"- ({pg}) {norm_space(m.get('point_zh', ''))}")
            lines.append("")
        if fey.get("difficulties"):
            lines.append("**本章标注的难点**")
            lines.append("")
            for d in fey["difficulties"]:
                pg = ", ".join(f"p.{p}" for p in d.get("source_pages", []))
                lines.append(f"- ({pg}) {norm_space(d.get('name_zh', ''))} —— {norm_space(d.get('why_hard_zh', ''))}")
            lines.append("")
        if note.get("terms"):
            terms = "、".join(f"{t.get('en')}({t.get('zh')})" for t in note["terms"][:40])
            lines += ["**本章术语**:" + terms, ""]
    return "\n".join(lines)


GROUP_TASK_MD = """# 面试复习笔记任务 — {title}

> 这是**协议级**任务:把 `{group_key}` 下已完成的 {chapter_count} 章笔记,
> 汇总成一份面试复习笔记。**与章节笔记不同,这里允许发散** —— 但发散必须放对位置。

## 0. 你的身份与目标

你是一位拥有 15 年经验的资深网络与安全架构专家、顶级大厂技术面试官,
同时精通费曼学习法。现在要为 `{title}` 出一份**能直接用于面试冲刺**的复习笔记:

1. **知识体系图** —— 把这几章串成一张图,给出复习顺序;
2. **跨章必须掌握清单** —— 面试前必须张口就答的;
3. **高频必考基础/原理题** —— 附**高分答题模板**与**得分要点**;
4. **场景化面试题(情景模拟)** —— 给具体现场,考解题框架;
5. **面试官连环追问** —— 每组正好**三层递进**深挖;
6. **避坑指南** —— 80% 候选人会踩的概念陷阱与错误回答。

问题与答案**全部中英双语**。

## 1. 输入(只读)

| 文件 | 用途 |
| --- | --- |
| `chapters.md` | 本协议各章的知识骨架(含 `pdf_id` 与页码),**出题素材只能来自这里** |
| `context.json` | 机器可读上下文(章节清单、阈值) |
| `interview.schema.json` | 输出结构 |
| `../../extract/<pdf_id>/text.md` | 需要复制英文原句时,回到这里取(路径见 context.json) |

覆盖的章节:

{chapter_list}

## 2. 输出

```
{output_path}
```

必须符合 `interview.schema.json`。Markdown 排版由 `nlnotes build-group` 渲染,**不要手写 Markdown**。

## 3. 发散的边界(本任务最重要的规则)

允许发散,但要**分栏放置**:

| 内容 | 放哪 | 校验方式 |
| --- | --- | --- |
| 题目的**核心答案**、原理、机制、数值、状态、判定顺序 | `answer_template_*` / `ideal_answer_*` / `layers[].answer_*` / `correct_*` | **严格校验**:必须能在 `grounding` 指向的原文页找到依据 |
| 工程经验、厂商差异、版本演进、生产实践、跨协议对比 | `extension_zh` / `extension_en` | 不做原文比对,但会被渲染成"⚠️ 课程外扩展"独立区块 |

也就是说:**课程里讲过的,答案要能追溯到原文;课程外的,必须显式标进 extension。**
把课程外的内容混进核心答案里,会被 `grounding` 门禁拦下。

每个 `fundamentals` / `scenarios` / `followups[].layers` / `pitfalls` 条目都必须至少有
1 条 `grounding`,格式:

```json
{{"pdf_id": "<来自 chapters.md>", "page": 3, "quote": "<该页英文原句,逐字复制>"}}
```

门禁比对阈值 **{quote_threshold}**;`pdf_id` 必须出现在 `covered_chapters` 里。

## 4. 数量要求

| 区块 | 最少 |
| --- | --- |
| `must_master` 跨章必须掌握 | {min_must} 条 |
| `fundamentals` 基础/原理题 | {min_fund} 道 |
| `scenarios` 场景题 | {min_scen} 道 |
| `followups` 连环追问组(每组正好 3 层) | {min_follow} 组 |
| `pitfalls` 避坑 | {min_pit} 条 |

## 5. 质量要求(比数量更重要)

- **杜绝空洞**:不要写"要深入理解 OSPF 邻居关系"这种话。
  每条都要有具体信息:机制、条件、数值、顺序、对比对象。
- **答题模板要能照着说**:`opening` 先给结论,`body` 分 2~5 段(每段有 `label`),
  `closing` 回扣问题或给适用边界。
- **得分要点要能打分**:面试官按 `scoring_points_*` 逐条勾,答到几条给几分。
- **场景题要具体到能动手**:写清拓扑、现象、已知条件,不要"某公司网络出现故障"。
  真正考的是 `thinking_framework_zh`(排查/推导顺序)。
- **连环追问要真的递进**:第 1 层问"是什么",第 2 层问"为什么/怎么做",
  第 3 层问"边界与代价"。每层写清 `probe_intent_zh`(面试官想验证什么)。
- **避坑要写候选人的原话**:`wrong_zh` 用"很多人会说……"的口吻写出典型错误说法,
  再说清错在哪、正确说法是什么。

## 6. 完成后自检

```bash
python -m nlnotes build-group --group {group_id}
```

会依次做:结构校验 → `grounding` 原文比对 → 中英双语纯度 → 数量与三层结构检查 →
渲染 Markdown。报告在 `build/reports/group-{group_id}.json`,按错误逐条修到通过。
"""


def build_group_task(cfg: Config, group: dict[str, Any], force: bool = False) -> Path:
    pairs = chapter_notes(cfg, group)
    if not pairs:
        raise FileNotFoundError(
            f"分组 {group['key']} 下还没有任何已完成的 note.json;"
            f"请先完成该协议的章节笔记(python -m nlnotes next --path {group['key']})")

    gdir = ensure_dir(group_dir(cfg, group["id"]))
    ensure_dir(gdir / "OUTPUT")
    write_text(gdir / "chapters.md",
               _chapters_md(pairs, int(cfg["group_chapters_budget_chars"])))
    shutil.copyfile(SCHEMA_PATH, gdir / "interview.schema.json")

    chapters_ctx = []
    for it, note in pairs:
        meta_path = cfg.extract_dir(it["id"]) / "extract.json"
        pages_total = read_json(meta_path).get("pages_total") if meta_path.exists() else None
        chapters_ctx.append({
            "pdf_id": it["id"],
            "title_zh": note.get("title_zh", it["title"]),
            "title_en": note.get("title_en", it["title"]),
            "rel_path": it["rel_path"],
            "pages_total": pages_total,
            "source_text": f"build/extract/{it['id']}/text.md",
        })

    note_rel = f"{group['key']}/00-面试复习-{group['title']}.md" if group["key"] != "(根目录)" \
        else f"00-面试复习-{group['title']}.md"

    write_json(gdir / "context.json", {
        "group_id": group["id"],
        "group_key": group["key"],
        "group_title": group["title"],
        "chapter_count": len(pairs),
        "chapters": chapters_ctx,
        "output_path": f"build/groups/{group['id']}/OUTPUT/interview.json",
        "note_output_markdown": note_rel,
        "gates": {
            "quote_match_threshold": cfg["interview_quote_threshold"],
            "min_must_master": cfg["interview_min_must_master"],
            "min_fundamentals": cfg["interview_min_fundamentals"],
            "min_scenarios": cfg["interview_min_scenarios"],
            "min_followups": cfg["interview_min_followups"],
            "min_pitfalls": cfg["interview_min_pitfalls"],
        },
    })

    chapter_list = "\n".join(
        f"- `{c['pdf_id']}` — {c['title_zh']}({c['pages_total']} 页)" for c in chapters_ctx)

    write_text(gdir / "TASK.md", GROUP_TASK_MD.format(
        title=group["title"], group_key=group["key"], group_id=group["id"],
        chapter_count=len(pairs), chapter_list=chapter_list,
        output_path=f"build/groups/{group['id']}/OUTPUT/interview.json",
        quote_threshold=cfg["interview_quote_threshold"],
        min_must=cfg["interview_min_must_master"],
        min_fund=cfg["interview_min_fundamentals"],
        min_scen=cfg["interview_min_scenarios"],
        min_follow=cfg["interview_min_followups"],
        min_pit=cfg["interview_min_pitfalls"],
    ))
    log(f"面试复习任务包就绪: {gdir}({len(pairs)} 章)", "ok")
    return gdir


# ------------------------------------------------------------------ 门禁

# 允许发散、因此不做原文比对的字段名后缀
EXTENSION_KEYS = ("extension_zh", "extension_en")


def _iter_grounded_text(interview: dict[str, Any]):
    """遍历"必须有原文依据"的中文字段 -> (定位, 文本)。extension_* 不在其中。"""
    for i, m in enumerate(interview.get("must_master", [])):
        yield f"must_master[{i}].point_zh", m.get("point_zh", "")
        yield f"must_master[{i}].why_zh", m.get("why_zh", "")
    for i, f in enumerate(interview.get("fundamentals", [])):
        base = f"fundamentals[{i}]({f.get('id')})"
        yield f"{base}.q_zh", f.get("q_zh", "")
        for lang in ("zh",):
            tpl = f.get(f"answer_template_{lang}", {}) or {}
            yield f"{base}.answer_template_{lang}.opening", tpl.get("opening", "")
            for bi, b in enumerate(tpl.get("body", []) or []):
                yield f"{base}.answer_template_{lang}.body[{bi}]", b.get("content", "")
            yield f"{base}.answer_template_{lang}.closing", tpl.get("closing", "")
        for si, s in enumerate(f.get("scoring_points_zh", []) or []):
            yield f"{base}.scoring_points_zh[{si}]", s
    for i, s in enumerate(interview.get("scenarios", [])):
        base = f"scenarios[{i}]({s.get('id')})"
        yield f"{base}.scene_zh", s.get("scene_zh", "")
        yield f"{base}.task_zh", s.get("task_zh", "")
        yield f"{base}.ideal_answer_zh", s.get("ideal_answer_zh", "")
        for ti, t in enumerate(s.get("thinking_framework_zh", []) or []):
            yield f"{base}.thinking_framework_zh[{ti}]", t
        for si, sp in enumerate(s.get("scoring_points_zh", []) or []):
            yield f"{base}.scoring_points_zh[{si}]", sp
    for i, u in enumerate(interview.get("followups", [])):
        base = f"followups[{i}]({u.get('id')})"
        yield f"{base}.root_q_zh", u.get("root_q_zh", "")
        for li, layer in enumerate(u.get("layers", []) or []):
            yield f"{base}.layers[{li}].q_zh", layer.get("q_zh", "")
            yield f"{base}.layers[{li}].answer_zh", layer.get("answer_zh", "")
    for i, p in enumerate(interview.get("pitfalls", [])):
        base = f"pitfalls[{i}]({p.get('id')})"
        yield f"{base}.wrong_zh", p.get("wrong_zh", "")
        yield f"{base}.why_wrong_zh", p.get("why_wrong_zh", "")
        yield f"{base}.correct_zh", p.get("correct_zh", "")


def _iter_grounding_blocks(interview: dict[str, Any]):
    """遍历所有 grounding 列表 -> (定位, grounding[])。"""
    for key in ("must_master", "fundamentals", "scenarios", "pitfalls"):
        for i, item in enumerate(interview.get(key, [])):
            yield f"{key}[{i}]", item.get("grounding", []) or []
    for i, u in enumerate(interview.get("followups", [])):
        for li, layer in enumerate(u.get("layers", []) or []):
            yield f"followups[{i}].layers[{li}]", layer.get("grounding", []) or []


def _iter_bilingual_pairs(interview: dict[str, Any]):
    """(定位, 中文文本, 英文文本) —— 用于双语纯度检查。"""
    for i, f in enumerate(interview.get("fundamentals", [])):
        yield f"fundamentals[{i}].q", f.get("q_zh", ""), f.get("q_en", "")
    for i, s in enumerate(interview.get("scenarios", [])):
        yield f"scenarios[{i}].scene", s.get("scene_zh", ""), s.get("scene_en", "")
        yield f"scenarios[{i}].ideal_answer", s.get("ideal_answer_zh", ""), s.get("ideal_answer_en", "")
    for i, u in enumerate(interview.get("followups", [])):
        yield f"followups[{i}].root_q", u.get("root_q_zh", ""), u.get("root_q_en", "")
        for li, layer in enumerate(u.get("layers", []) or []):
            yield (f"followups[{i}].layers[{li}].answer",
                   layer.get("answer_zh", ""), layer.get("answer_en", ""))
    for i, p in enumerate(interview.get("pitfalls", [])):
        yield f"pitfalls[{i}].correct", p.get("correct_zh", ""), p.get("correct_en", "")


def verify_interview(cfg: Config, group: dict[str, Any],
                     interview: dict[str, Any] | None = None):
    from nlnotes.verify import Report
    from nlnotes.util import has_cjk

    rep = Report(f"group-{group['id']}")
    if interview is None:
        p = interview_path(cfg, group["id"])
        if not p.exists():
            rep.err("S000", "interview.json", f"未找到 {p}",
                    f"先按 build/groups/{group['id']}/TASK.md 产出 interview.json")
            return rep
        try:
            interview = read_json(p)
        except Exception as exc:
            rep.err("S000", "interview.json", f"JSON 解析失败: {exc}", "检查 JSON 语法")
            return rep

    # --- 结构 ---
    try:
        import jsonschema
        validator = jsonschema.Draft7Validator(read_json(SCHEMA_PATH))
        errs = sorted(validator.iter_errors(interview), key=lambda e: list(e.path))
        for e in errs[:40]:
            loc = "/".join(str(x) for x in e.path) or "(根)"
            rep.err("S001", loc, f"结构不符合 schema: {e.message}",
                    "对照 interview.schema.json 修正")
        if errs:
            _write_group_report(cfg, rep)
            return rep
    except ImportError:
        rep.warn("S000", "schema", "未安装 jsonschema,跳过结构校验", "pip install jsonschema")

    # --- 分组键一致性 ---
    declared = str(interview.get("group_key", "")).strip()
    if declared and declared != group["key"]:
        rep.err("A005", "group_key",
                f"group_key 与实际分组不一致:写的是 “{declared}”,应为 “{group['key']}”",
                f"改成 {group['key']}(见任务包 context.json 的 group_key)")

    # --- 章节范围 ---
    available = {it["id"] for it in group["items"]}
    have_notes = {it["id"] for it, _ in chapter_notes(cfg, group)}
    covered = [c.get("pdf_id") for c in interview.get("covered_chapters", [])]
    for pid in covered:
        if pid not in available:
            rep.err("A001", "covered_chapters", f"pdf_id 不属于本分组: {pid}",
                    "只能覆盖 context.json 里列出的章节")
        elif pid not in have_notes:
            rep.err("A002", "covered_chapters",
                    f"该章节还没有 note.json,不能作为出题素材: {pid}",
                    "先完成该章节的笔记")
    missing = sorted(have_notes - set(covered))
    if missing:
        rep.warn("A003", "covered_chapters",
                 f"本组有 {len(missing)} 章已完成但未纳入复习笔记: {missing[:8]}",
                 "补进 covered_chapters,否则面试复习会漏内容")

    # --- 加载各章证据索引 ---
    indexes: dict[str, SourceIndex] = {}
    for pid in set(covered) & have_notes:
        try:
            indexes[pid] = SourceIndex.load(cfg.extract_dir(pid))
        except Exception as exc:
            rep.err("A004", f"chapter({pid})", f"无法加载该章抽取产物: {exc}",
                    f"重跑 python -m nlnotes extract --id {pid}")

    # --- grounding 比对 ---
    th = int(cfg["interview_quote_threshold"])
    checked = matched = 0
    for where, blocks in _iter_grounding_blocks(interview):
        if not blocks:
            rep.err("G001", where, "缺少 grounding(至少 1 条原文依据)",
                    "补上 {pdf_id, page, quote}")
            continue
        for gi, g in enumerate(blocks):
            pid, page, quote = g.get("pdf_id"), int(g.get("page", 0)), g.get("quote", "")
            loc = f"{where}.grounding[{gi}]"
            idx = indexes.get(pid)
            if idx is None:
                rep.err("G002", loc, f"grounding 引用了未覆盖的章节: {pid}",
                        "pdf_id 必须出现在 covered_chapters 中")
                continue
            if page < 1 or page > idx.pages_total:
                rep.err("G003", loc,
                        f"页码超出范围(该章共 {idx.pages_total} 页): {page}", "修正页码")
                continue
            checked += 1
            score, _ = idx.quote_score(quote, [page])
            if score >= th:
                matched += 1
                continue
            wide, wide_page = idx.quote_score(quote, None)
            if wide >= th:
                rep.err("G004", loc,
                        f"页码错误:该句在第 {wide_page} 页(相似度 {wide}),而不是第 {page} 页",
                        f"页码改成 {wide_page}")
            else:
                rep.err("G005", loc,
                        f"引用与原文不匹配(最高相似度 {max(score, wide)} < {th}): "
                        f"“{norm_space(quote)[:80]}”",
                        f"回到 build/extract/{pid}/text.md 逐字复制")
    rep.stats["grounding_checked"] = checked
    rep.stats["grounding_matched"] = matched

    # --- 受约束字段的 token 依据(合并本组所有章节的原文作为证据库) ---
    if cfg["interview_token_grounding"] and indexes:
        from nlnotes.evidence import SOURCE_TOKEN, load_glossary
        from nlnotes.util import norm_for_match
        whitelist = set(cfg["token_whitelist"]) | {t.en.lower() for t in load_glossary()}
        # 各章笔记登记过的图内标签(R1/Gi0/1/网段)同样是合法证据
        for _it, _note in chapter_notes(cfg, group):
            for sec in _note.get("sections", []):
                for fig in sec.get("figures", []) or []:
                    for label in fig.get("labels_seen", []) or []:
                        whitelist |= set(SOURCE_TOKEN.findall(norm_for_match(str(label))))
        bad_total = 0
        for where, text in _iter_grounded_text(interview):
            if not text:
                continue
            # 只要在本组任意一章里有依据就算通过(面试题本身就是跨章的)
            leftovers: list[str] | None = None
            for idx in indexes.values():
                bad = idx.ungrounded_tokens(str(text), whitelist)
                if not bad:
                    leftovers = []
                    break
                leftovers = bad if leftovers is None else [b for b in leftovers if b in bad]
            if leftovers:
                bad_total += len(leftovers)
                rep.err("T001", where,
                        f"出现本协议课程原文中找不到的技术词/数字: {', '.join(leftovers[:8])}"
                        + (" ..." if len(leftovers) > 8 else ""),
                        "若是课程外的工程经验,请移到 extension_zh / extension_en;"
                        "若是笔误,改用原文的说法")
        rep.stats["ungrounded_tokens"] = bad_total

    # --- 双语纯度 ---
    for where, zh, en in _iter_bilingual_pairs(interview):
        if zh and not has_cjk(zh):
            rep.err("X001", f"{where}_zh", "中文字段里没有中文", "补写中文版")
        if en and has_cjk(en):
            rep.err("X002", f"{where}_en", "英文字段里混入了中文", "英文字段必须是纯英文")

    # --- 数量与结构 ---
    counts = {
        "must_master": (len(interview.get("must_master", [])), cfg["interview_min_must_master"]),
        "fundamentals": (len(interview.get("fundamentals", [])), cfg["interview_min_fundamentals"]),
        "scenarios": (len(interview.get("scenarios", [])), cfg["interview_min_scenarios"]),
        "followups": (len(interview.get("followups", [])), cfg["interview_min_followups"]),
        "pitfalls": (len(interview.get("pitfalls", [])), cfg["interview_min_pitfalls"]),
    }
    for key, (got, need) in counts.items():
        rep.stats[key] = got
        if got < int(need):
            rep.err("X003", key, f"数量不足:{got} < {need}", "补足条目")

    for i, u in enumerate(interview.get("followups", [])):
        levels = [l.get("level") for l in u.get("layers", []) or []]
        if levels != [1, 2, 3]:
            rep.err("X004", f"followups[{i}]({u.get('id')}).layers",
                    f"连环追问必须正好三层且 level 依次为 1/2/3,当前为 {levels}",
                    "调整为三层递进")

    # --- id 唯一 ---
    for key in ("fundamentals", "scenarios", "followups", "pitfalls"):
        seen: set[str] = set()
        for item in interview.get(key, []):
            iid = item.get("id", "")
            if iid in seen:
                rep.err("S002", f"{key}({iid})", f"id 重复: {iid}", "改成唯一 id")
            seen.add(iid)

    # --- 发散措辞:面试笔记允许工程经验,但仍禁止"据说/我猜"这类不确定表述 ---
    for where, text in _iter_grounded_text(interview):
        for phrase in ("据说", "我猜", "大概是", "应该是吧", "不太确定"):
            if phrase and phrase in str(text):
                rep.err("F001", where, f"出现不确定表述:“{phrase}”",
                        "面试答案必须确定;不确定的内容不要写")

    _write_group_report(cfg, rep)
    return rep


def _write_group_report(cfg: Config, rep) -> None:
    out = cfg.report_dir() / f"{rep.pdf_id}.json"
    write_json(out, rep.to_dict())
    log(f"校验 {rep.pdf_id}: {'通过' if rep.passed else '未通过'} — "
        f"{len(rep.errors)} 错误 / {len(rep.warnings)} 警告 -> {out}",
        "ok" if rep.passed else "error")
