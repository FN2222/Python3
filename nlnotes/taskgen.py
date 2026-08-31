"""阶段 3 —— 为每个 PDF 生成"自包含任务包",AI 打开任务包就能干活。

build/tasks/<pdf_id>/
    TASK.md              总指令(硬约束 + 输出要求 + 自检清单)
    source-text.md       带 [[p.N]] 页码标记的原文全文(只读)
    figures.md           本章可用图清单(图注推测 + 周边上下文 + 预览路径)
    glossary.md          本章命中的术语与统一中文译名
    codeblocks.md        原文中的配置/命令块(可逐字引用)
    context.json         机器可读上下文
    note.schema.json     输出结构定义(副本,方便离线校验)
    note.template.json   骨架模板,照着填
    OUTPUT/              AI 把 note.json 写在这里
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from nlnotes.config import REPO_ROOT, Config
from nlnotes.evidence import SourceIndex, glossary_hits, load_glossary
from nlnotes.util import (copy_file, ensure_dir, log, norm_space, read_json, rel_posix,
                          write_json, write_text)

SCHEMA_PATH = REPO_ROOT / "schemas" / "note.schema.json"


# ------------------------------------------------------------------ 文档片段

def _figures_md(index: SourceIndex, task_dir: Path, extract_dir: Path) -> str:
    figs = index.figures
    lines = ["# 本章可用图片清单(只能引用下表中的 figure_id)", ""]
    if not figs:
        lines += ["> 本章 PDF 未抽取到可用图片。",
                  "> 因此 note.json 里 `figures` 应为空数组,",
                  "> 并且必须用 `visuals`(packet_flow / mermaid / graphviz)自制图来补足可视化。", ""]
        return "\n".join(lines)

    lines += [f"共 {len(figs)} 张。`预览` 列是相对本文件的路径,可直接打开查看。", "",
              "| figure_id | 页码 | 类型 | 尺寸 | 推测图注 | 上方标题 | 预览 |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for f in figs:
        preview = rel_posix(extract_dir / "figures" / f["file"], task_dir)
        lines.append(
            f"| `{f['figure_id']}` | {f['page']} | {f['kind']} | {f['width']}x{f['height']} | "
            f"{norm_space(f['caption_guess'])[:60] or '-'} | "
            f"{norm_space(f['heading_above'])[:40] or '-'} | [{f['file']}]({preview}) |")

    lines += ["", "> ⚠️ **重要**:拓扑图里的设备名、接口名、网段这些文字**存在于图片像素中,不在 PDF 文本层**。",
              "> 所以引用某张图时,必须在 `figures[].labels_seen` 里把你从图上读到的标签逐字登记,",
              "> 否则笔记里写 `R1`、`10.0.0.0/24` 会被门禁判为臆想。", ""]
    lines += ["## 每张图的原文周边上下文(判断这张图在讲什么)", ""]
    for f in figs:
        lines += [f"### `{f['figure_id']}` — 第 {f['page']} 页",
                  "", f"- 推测图注: {norm_space(f['caption_guess']) or '(无)'}",
                  f"- 上方标题: {norm_space(f['heading_above']) or '(无)'}"]
        ocr = norm_space(f.get("ocr_text", ""))
        if ocr:
            lines.append(f"- OCR 识别到的图内文字: `{ocr[:400]}`")
        lines += ["", "```text", norm_space(f["context"]) or "(无上下文)", "```", ""]
    return "\n".join(lines)


def _glossary_md(hits: list[dict[str, Any]]) -> str:
    lines = ["# 本章术语与统一译名", "",
             "以下术语在本章原文中真实出现。写笔记时**必须使用 `中文译名` 列的译法**,",
             "首次出现写成 `中文译名(English)`。",
             "**缩写仅当本章原文出现过该缩写时才能用**(原文只写全称就写全称;",
             "`terms[].en` 也必须是本章原文的实际用词,不要自行展开或缩写)。", "",
             "| 英文 | 中文译名 | 首次出现页 | 分类 |", "| --- | --- | --- | --- |"]
    for h in hits:
        lines.append(f"| {h['en']} | {h['zh']} | {h['first_page'] or '-'} | {h['category'] or '-'} |")
    if not hits:
        lines.append("| (术语表未命中,按原文直译并在 terms 中登记) | - | - | - |")
    lines += ["", "> 若原文出现了术语表里没有的关键术语,请在 note.json 的 `terms` 中补充登记,",
              "> 并给出你采用的中文译名与页码。", ""]
    return "\n".join(lines)


def _codeblocks_md(index: SourceIndex) -> str:
    blocks = index.codeblocks
    lines = ["# 原文中的配置 / 命令块(等宽字体自动识别)", ""]
    if not blocks:
        lines += ["> 本章未识别到等宽代码块。若原文正文中含命令,请直接从 source-text.md 逐字复制。", ""]
        return "\n".join(lines)
    lines += [f"共 {len(blocks)} 段。**引用时必须逐字复制,禁止改写、补全或修正。**", ""]
    for i, b in enumerate(blocks, start=1):
        lines += [f"## 块 {i} — 第 {b['page']} 页({b['lines']} 行)", "", "```text", b["code"], "```", ""]
    return "\n".join(lines)


def _sections_md(index: SourceIndex) -> str:
    if not index.sections:
        return "(未能识别标题层级,请自行按原文段落划分小节)"
    src = index.sections[0].get("source", "font")
    lines = [f"识别来源: {'PDF 书签' if src == 'toc' else '字号推断'}", ""]
    for s in index.sections[:80]:
        lines.append(f"{'  ' * (int(s.get('level', 1)) - 1)}- (p.{s['page']}) {s['title']}")
    return "\n".join(lines)


TASK_MD = """# 制作任务 — {title}

> 本文件是**唯一入口**。请严格按此执行,不要引入任何本任务包之外的知识。

## 0. 任务目标

把英文 PDF 课程《{title}》做成一份**中文学习笔记**,要求:

1. 知识点配上**原文中的拓扑图**(引用 `figures.md` 中的 figure_id)。
2. 抽象/难懂的地方,用**自制动画或分步静态图**讲清楚(`visuals`,由本工具渲染,不需要你画)。
3. 章末用**费曼学习法**出题检验,题目与答案都要**中英文双版**。
4. **严格限定在本章原文范围内**:不发散、不臆想、不补充课外知识。

## 1. 输入(全部只读,禁止修改)

| 文件 | 用途 |
| --- | --- |
| `source-text.md` | 原文全文,每页以 `[[p.N]]` 开头,页码引用必须与之一致 |
| `figures.md` | 可用图片清单 + 每张图的原文上下文 |
| `glossary.md` | 本章术语的统一中文译名 |
| `codeblocks.md` | 原文中的配置/命令块(可逐字引用) |
| `context.json` | 机器可读上下文(页数、图列表、阈值等) |
| `note.schema.json` | 你的输出必须符合的结构 |
| `note.template.json` | 骨架模板,照着填最省事 |

源 PDF: `{rel_path}` — **只读,永远不要改动或移动它。**

## 2. 输出

只需产出**一个文件**:

```
{output_path}
```

它必须是符合 `note.schema.json` 的 JSON。Markdown 排版、图片拷贝、动画渲染、
测验排版全部由 `nlnotes build` 自动完成,**你不要手写 Markdown**。

## 3. 硬约束(违反即门禁失败)

### 3.1 每条知识点必须有原文出处

`sections[].points[]` 每一项都要:

- `text_en_quote`: 从 `source-text.md` **同一页、连续的一段**逐字复制,
  长度 ≥ 12 字符。门禁会把它和你声明的那一页做模糊比对,阈值 **{quote_threshold}**。
  ` ... ` 只允许省略**同一句话内部**的从句;禁止跨 `[[p.N]]` 拼两页,
  禁止用省略号把命令输出里不相邻的行拼成一句。需要两处原文就写两条 point。
- `page`: 该句所在页码(1 ~ {pages_total})。
- `text_zh`: 这句话的中文讲解。**只能翻译/解释 `text_en_quote` 里已有的信息**,
  不得添加原文没有的例子、数字、协议、结论、生产经验。
- `kind`: 只能是 `fact` / `definition` / `mechanism` / `step` / `caveat` /
  `example` / `command`。**不要填 `process`**(那是费曼题目的 `type`)。
- `detail_zh`: `mechanism` / `step` / `caveat` / `definition` **必须填**,
  把机制、前提、例外讲透(仍只能用原文)。全章目标:密度 ≥ 3.0 条/正文页,
  至少约 1/4 的知识点有深入说明。不要贴着 2.0 门槛停。

### 3.2 禁止出现原文没有的技术词与数字

门禁会扫描你所有中文字段里的英文单词、IP 地址、数字(≥2 位),
逐个检查是否出现在原文中。**编造一个协议名、一个定时器数值、一个 IP,都会直接失败。**

特别容易踩的坑:

- 原文只写全称(`area border router`)就不要自行缩成 `ABR`;原文只写 `DR` 就不要在
  `terms[].en` 里展开成本章没出现的 `Designated Router`
- 掩码写法不许换算:原文是 `255.255.255.0` 就不要写成 `/24`,反之亦然
- 中文字段不要写原文没有的 `vs`;讲解里不要出现 `fig-p001-1` 这种 figure_id
- 本章边界用「本章不涉及 X」,不要写禁用词「超出本章」

### 3.3 禁止发散措辞

以下词一律不得出现:{forbidden}

### 3.4 图片只能引用真实存在的,且必须登记图上标签

`figures[].figure_id` 必须来自 `figures.md`。本章共有 **{figure_count}** 张可用图,
门禁要求至少引用其中 **{min_fig_ref}** 张(可用图为 0 时不做此要求)。

拓扑图里的设备名(R1/SW1)、接口名、网段(10.0.0.0/24)这些文字**只存在于图片像素里,
不在 PDF 文本层**。因此:**打开 `figures.md` 里给出的图片预览路径看图**,
把你读到的标签逐字填进 `figures[].labels_seen`。登记过的标签才允许出现在中文讲解中。
未登记就使用 `R2`、`192.168.12.0/24` 之类的字样,会被判为臆想。

### 3.5 内容覆盖度

被引用的页码必须覆盖正文页的 **{coverage:.0%}** 以上
(本章正文页共 {content_pages_count} 页,页号见 `context.json` 的 `content_pages`)。
不允许只挑简单段落做,漏掉大段内容。

### 3.6 配置/命令逐字引用

`configs[].code` 必须逐字复制原文,不得改写、补全、纠错、翻译。
中文解释写在 `explain_zh` / `annotations_zh` 里。

## 4. 自制可视化(`sections[].visuals[]`)怎么写

**判断标准:只有当原文的某个点"抽象、多步骤、时序性强、容易混淆"时才自制图。**
每个 visual 都必须填 `why_zh`(说明原文哪个点难懂)和 `grounding`
(≥1 条支撑本图元素的英文原文引用,门禁阈值 {visual_threshold})。

五种 `kind`:

### `packet_flow` — 首选,用于"报文/状态一步步变化"
本工具会渲染成**动画 GIF + 分步静态图 PNG(+MP4)**。规格:

```json
{{
  "kind": "packet_flow",
  "spec": {{
    "nodes": [
      {{"id": "R1", "label": "R1", "role": "router", "x": 0.0, "y": 0.35}},
      {{"id": "R2", "label": "R2", "role": "router", "x": 1.0, "y": 0.35}}
    ],
    "links": [{{"from": "R1", "to": "R2", "label": "10.1.1.0/24"}}],
    "steps": [
      {{"title_zh": "R1 发出 Hello",
        "note_zh": "原文说明这一步做什么(仍须来自原文)",
        "packets": [{{"from": "R1", "to": "R2", "label": "Hello"}}],
        "highlight_nodes": ["R1"],
        "highlight_links": [["R1", "R2"]],
        "state": {{"R1": "Init"}}}}
    ]
  }}
}}
```

- `role` 可选: router / switch / host / server / cloud / firewall
- `x`、`y` 为 0~1 相对坐标(不填则自动布局)
- `steps` 建议 3~8 步;`label`、`state` 里的英文必须来自原文
- 节点名(R1/SW1/H1)必须是原文或原文拓扑图里出现过的名字

### `mermaid` — 用于结构、流程判定、层级关系
`spec.code` 写 mermaid 源码(`flowchart` / `sequenceDiagram` / `stateDiagram-v2`)。
装了 mermaid-cli 就渲染成 PNG,否则内联代码块(Obsidian/Typora/GitHub 均可显示)。

### `graphviz` — 用于状态机、树形结构
`spec.dot` 写 DOT 源码。

### `comparison_table` — 用于"A 与 B 的区别"
`spec.headers` + `spec.rows`,内容必须逐项能在原文找到依据。

### `ai_illustration` — 仅用于确实需要类比/隐喻的极抽象概念
`spec.prompt_en`(英文提示词)+ `spec.must_include_labels`(图中允许出现的唯一文字)。
渲染后会自动打上"AI 辅助示意图 · 非 PDF 原图"水印。**每章最多 1 个,能用前四种就不要用这个。**

## 5. 费曼测验(`feynman`)

1. `explain_back_zh`:用最朴素的中文把本章讲给外行听(≥80 字,少用术语),内容仍须来自原文。
2. `questions`:**{min_q} ~ {max_q} 题**,每题必须含
   `q_zh` / `q_en` / `answer_zh` / `answer_en` / `source_pages` / `evidence_quote`。
   - 中英文必须是**同一道题**的两个语言版本,不能是两道不同的题。
   - `answer_en` 应尽量贴合原文表述;`answer_zh` 是它的中文版,至少 25 字。
   - `must_master[].why_zh` 至少 15 字。
   - `type` 至少覆盖 {required_types};建议按 `difficulty` 1→3 递进。
   - **题目不得超纲**:凡是本章原文没讲的,不能出题。
3. `blind_spots_zh`:本章最容易卡住的点(仍须来自原文内容)。

## 6. 完成后必须自检

```bash
python -m nlnotes build --id {pdf_id}
```

该命令会依次执行:结构校验 → 原文引用比对 → token 依据检查 → 覆盖度检查 →
渲染可视化 → 生成 Markdown。**若报错,请按报错逐条修正 `note.json` 后重跑,
直到 `verify` 全绿。** 报告在 `build/reports/{pdf_id}.json`。

常见失败与处理:

| 报错 | 原因 | 处理 |
| --- | --- | --- |
| `引用与原文不匹配` | `text_en_quote` 跨页、拼接了不相邻的命令行、或页码写错 | 同一页连续复制;两条原文就写两条 point |
| `无原文依据的 token` | 擅自缩写、换算掩码、写了 `vs` / figure_id、或编造了词 | 改用原文里的说法 |
| `schema 不合格` | `kind` 误填 `process`,或 `why_zh` / `answer_zh` 太短 | 对照 `note.schema.json` |
| `figure_id 不存在` | 图 id 写错 | 对照 `figures.md` |
| `覆盖度不足` | 漏掉大段内容 | 补充对应页的 sections/points |
| `引用页码超范围` | 页码 > {pages_total} | 修正页码 |
"""


def _template(item: dict[str, Any], index: SourceIndex) -> dict[str, Any]:
    first_fig = index.figures[0]["figure_id"] if index.figures else None
    section: dict[str, Any] = {
        "id": "s1",
        "heading_zh": "(中文小节标题)",
        "heading_en": "(原文对应英文标题)",
        "pages": [1],
        "intro_zh": "",
        "points": [{
            "text_zh": "(中文讲解,只解释下面这句英文里已有的信息)",
            "text_en_quote": "(从 source-text.md 逐字复制的英文原句)",
            "page": 1,
            "kind": "fact",
        }],
        "figures": ([{"figure_id": first_fig,
                      "caption_zh": "(中文图注)",
                      "explain_zh": "(结合原文说明图中各设备/链路的角色)",
                      "callouts_zh": [],
                      "labels_seen": ["(从图上逐字读到的标签,如 R1)"]}] if first_fig else []),
        "visuals": [{
            "id": "v1",
            "kind": "packet_flow",
            "title_zh": "(图标题)",
            "why_zh": "(原文哪个点抽象,所以需要自制图)",
            "caption_zh": "",
            "source_pages": [1],
            "grounding": ["(支撑本图的英文原文引用)"],
            "spec": {
                "nodes": [{"id": "R1", "label": "R1", "role": "router", "x": 0.0, "y": 0.35},
                          {"id": "R2", "label": "R2", "role": "router", "x": 1.0, "y": 0.35}],
                "links": [{"from": "R1", "to": "R2", "label": ""}],
                "steps": [{"title_zh": "(第一步)", "note_zh": "",
                           "packets": [{"from": "R1", "to": "R2", "label": ""}],
                           "highlight_nodes": ["R1"], "highlight_links": [["R1", "R2"]],
                           "state": {}}],
            },
        }],
        "configs": [],
        "tables": [],
    }
    return {
        "pdf_id": item["id"],
        "source_rel_path": item["rel_path"],
        "title_en": index.meta.get("title", item["title"]),
        "title_zh": "(中文标题)",
        "summary_zh": "(3-5 句:本章讲什么、解决什么问题,全部来自原文)",
        "scope_zh": "(本章边界:覆盖 X、Y;不涉及 Z)",
        "prerequisites_zh": [],
        "sections": [section],
        "key_takeaways_zh": ["(要点 1)", "(要点 2)", "(要点 3)"],
        "terms": [{"en": "OSPF", "zh": "开放最短路径优先", "page": 1, "note_zh": ""}],
        "feynman": {
            "explain_back_zh": "(≥80 字,用最朴素的中文把本章讲给外行听)",
            "questions": [{
                "id": "q1", "type": "concept", "difficulty": 1,
                "q_zh": "(中文问题)", "q_en": "(English question — same question)",
                "answer_zh": "(中文答案)", "answer_en": "(English answer)",
                "source_pages": [1],
                "evidence_quote": "(答案依据的英文原句)",
                "figure_refs": [], "scoring_points_zh": [],
            }],
            "blind_spots_zh": [],
            "review_plan_zh": [],
        },
    }


# ------------------------------------------------------------------ 主流程

def build_task(cfg: Config, item: dict[str, Any], force: bool = False) -> Path:
    extract_dir = cfg.extract_dir(item["id"])
    if not (extract_dir / "extract.json").exists():
        raise FileNotFoundError(f"请先抽取该 PDF: nlnotes extract --id {item['id']}")

    index = SourceIndex.load(extract_dir)
    task_dir = ensure_dir(cfg.task_dir(item["id"]))
    out_dir = ensure_dir(task_dir / "OUTPUT")
    hits = glossary_hits(index, load_glossary())

    copy_file(extract_dir / "text.md", task_dir / "source-text.md")
    write_text(task_dir / "figures.md", _figures_md(index, task_dir, extract_dir))
    write_text(task_dir / "glossary.md", _glossary_md(hits))
    write_text(task_dir / "codeblocks.md", _codeblocks_md(index))
    write_text(task_dir / "outline.md",
               "# 原文标题层级\n\n" + _sections_md(index) + "\n")
    copy_file(SCHEMA_PATH, task_dir / "note.schema.json")

    tpl_path = task_dir / "note.template.json"
    if force or not tpl_path.exists():
        write_json(tpl_path, _template(item, index))

    figure_count = len(index.figures)
    min_fig_ref = (max(1, int(round(figure_count * cfg["min_figure_reference_ratio"])))
                   if figure_count and cfg["require_figure_when_available"] else 0)

    write_json(task_dir / "context.json", {
        "pdf_id": item["id"],
        "title": item["title"],
        "source_rel_path": item["rel_path"],
        "course_path": item["course_path"],
        "pages_total": index.pages_total,
        "content_pages": index.content_pages,
        "figures": [{k: f[k] for k in ("figure_id", "file", "page", "kind",
                                       "caption_guess", "heading_above")}
                    for f in index.figures],
        "sections_detected": index.sections[:80],
        "codeblock_count": len(index.codeblocks),
        "glossary_hits": hits,
        "output_path": rel_posix(out_dir / "note.json", cfg.build_dir.parent),
        "note_output_markdown": rel_posix(cfg.notes_dir / item["note_rel_path"],
                                          cfg.build_dir.parent),
        "gates": {
            "quote_match_threshold": cfg["quote_match_threshold"],
            "visual_quote_threshold": cfg["visual_quote_threshold"],
            "coverage_min_ratio": cfg["coverage_min_ratio"],
            "min_questions": cfg["min_questions"],
            "max_questions": cfg["max_questions"],
            "required_question_types": cfg["required_question_types"],
            "min_figure_references": min_fig_ref,
            "forbidden_phrases": cfg["forbidden_phrases"],
        },
    })

    write_text(task_dir / "TASK.md", TASK_MD.format(
        title=item["title"],
        rel_path=item["rel_path"],
        pdf_id=item["id"],
        output_path=rel_posix(out_dir / "note.json", cfg.build_dir.parent),
        pages_total=index.pages_total,
        content_pages_count=len(index.content_pages),
        figure_count=figure_count,
        min_fig_ref=min_fig_ref,
        quote_threshold=cfg["quote_match_threshold"],
        visual_threshold=cfg["visual_quote_threshold"],
        coverage=cfg["coverage_min_ratio"],
        min_q=cfg["min_questions"],
        max_q=cfg["max_questions"],
        required_types="、".join(cfg["required_question_types"]),
        forbidden="、".join(cfg["forbidden_phrases"][:10]) + " 等",
    ))

    log(f"任务包就绪: {task_dir}", "ok")
    return task_dir


def build_tasks(cfg: Config, items: list[dict[str, Any]], force: bool = False) -> list[Path]:
    dirs = []
    for it in items:
        try:
            dirs.append(build_task(cfg, it, force=force))
        except Exception as exc:
            log(f"生成任务包失败 {it['rel_path']}: {exc}", "error")
    return dirs


def note_path(cfg: Config, pdf_id: str) -> Path:
    return cfg.task_dir(pdf_id) / "OUTPUT" / "note.json"


def pending_items(cfg: Config, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """还没写 note.json 的 PDF。"""
    return [it for it in items if not note_path(cfg, it["id"]).exists()]
