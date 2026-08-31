"""阶段 5 —— 质量门禁:机械校验"笔记有没有超出原文"。

分为 9 组检查:
  S  结构        note.json 是否符合 schema、id 是否唯一
  P  页码        引用页是否存在、是否越界
  Q  原文引用    text_en_quote / evidence_quote / grounding 是否真的出现在它声明的那一页
  T  token 依据  中文里出现的英文词、IP、数字是否有原文依据(抓"编造")
  F  发散措辞    禁用词
  G  图片        figure_id 是否真实存在、引用比例是否达标
  C  配置        configs[].code 是否逐字来自原文
  V  可视化      每个自制图是否有 grounding 支撑
  X  覆盖 & 测验 内容覆盖度、题目数量/类型/中英双语配对

errors 非空 => 门禁不通过,笔记不予发布。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from nlnotes.config import REPO_ROOT, Config
from nlnotes.evidence import SourceIndex, load_glossary
from nlnotes.util import has_cjk, log, norm_space, read_json, write_json

SCHEMA_PATH = REPO_ROOT / "schemas" / "note.schema.json"


class Report:
    def __init__(self, pdf_id: str) -> None:
        self.pdf_id = pdf_id
        self.errors: list[dict[str, Any]] = []
        self.warnings: list[dict[str, Any]] = []
        self.stats: dict[str, Any] = {}

    def err(self, code: str, where: str, msg: str, fix: str = "") -> None:
        self.errors.append({"code": code, "where": where, "message": msg, "fix": fix})

    def warn(self, code: str, where: str, msg: str, fix: str = "") -> None:
        self.warnings.append({"code": code, "where": where, "message": msg, "fix": fix})

    @property
    def passed(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {"pdf_id": self.pdf_id, "passed": self.passed,
                "error_count": len(self.errors), "warning_count": len(self.warnings),
                "stats": self.stats, "errors": self.errors, "warnings": self.warnings}


# ------------------------------------------------------------------ 字段收集

def iter_zh_fields(note: dict[str, Any]) -> Iterable[tuple[str, str]]:
    """遍历所有"应当受原文约束"的中文字段 -> (定位, 文本)。"""
    yield "summary_zh", note.get("summary_zh", "")
    yield "scope_zh", note.get("scope_zh", "")
    for i, t in enumerate(note.get("prerequisites_zh", []) or []):
        yield f"prerequisites_zh[{i}]", t
    for i, t in enumerate(note.get("key_takeaways_zh", []) or []):
        yield f"key_takeaways_zh[{i}]", t

    for si, sec in enumerate(note.get("sections", [])):
        base = f"sections[{si}]({sec.get('id', '?')})"
        yield f"{base}.heading_zh", sec.get("heading_zh", "")
        if sec.get("intro_zh"):
            yield f"{base}.intro_zh", sec["intro_zh"]
        for pi, pt in enumerate(sec.get("points", [])):
            yield f"{base}.points[{pi}].text_zh", pt.get("text_zh", "")
            if pt.get("detail_zh"):
                yield f"{base}.points[{pi}].detail_zh", pt["detail_zh"]
        for fi, fig in enumerate(sec.get("figures", []) or []):
            yield f"{base}.figures[{fi}].caption_zh", fig.get("caption_zh", "")
            yield f"{base}.figures[{fi}].explain_zh", fig.get("explain_zh", "")
            for ci, c in enumerate(fig.get("callouts_zh", []) or []):
                yield f"{base}.figures[{fi}].callouts_zh[{ci}]", c
        for vi, v in enumerate(sec.get("visuals", []) or []):
            vb = f"{base}.visuals[{vi}]({v.get('id', '?')})"
            yield f"{vb}.title_zh", v.get("title_zh", "")
            yield f"{vb}.why_zh", v.get("why_zh", "")
            if v.get("caption_zh"):
                yield f"{vb}.caption_zh", v["caption_zh"]
            for sti, st in enumerate((v.get("spec", {}) or {}).get("steps", []) or []):
                yield f"{vb}.spec.steps[{sti}].title_zh", st.get("title_zh", "")
                if st.get("note_zh"):
                    yield f"{vb}.spec.steps[{sti}].note_zh", st["note_zh"]
        for ci, cb in enumerate(sec.get("configs", []) or []):
            yield f"{base}.configs[{ci}].explain_zh", cb.get("explain_zh", "")
            for ai, an in enumerate(cb.get("annotations_zh", []) or []):
                yield f"{base}.configs[{ci}].annotations_zh[{ai}].note_zh", an.get("note_zh", "")
        for ti, tb in enumerate(sec.get("tables", []) or []):
            yield f"{base}.tables[{ti}].title_zh", tb.get("title_zh", "")

    fey = note.get("feynman", {}) or {}
    yield "feynman.explain_back_zh", fey.get("explain_back_zh", "")
    for mi, m in enumerate(fey.get("must_master", []) or []):
        yield f"feynman.must_master[{mi}].point_zh", m.get("point_zh", "")
        yield f"feynman.must_master[{mi}].why_zh", m.get("why_zh", "")
        if m.get("memory_hook_zh"):
            yield f"feynman.must_master[{mi}].memory_hook_zh", m["memory_hook_zh"]
    for di, d in enumerate(fey.get("difficulties", []) or []):
        yield f"feynman.difficulties[{di}].name_zh", d.get("name_zh", "")
        yield f"feynman.difficulties[{di}].why_hard_zh", d.get("why_hard_zh", "")
        yield f"feynman.difficulties[{di}].how_to_break_zh", d.get("how_to_break_zh", "")
    for qi, q in enumerate(fey.get("questions", []) or []):
        yield f"feynman.questions[{qi}]({q.get('id', '?')}).q_zh", q.get("q_zh", "")
        yield f"feynman.questions[{qi}]({q.get('id', '?')}).answer_zh", q.get("answer_zh", "")
        for si2, sp in enumerate(q.get("scoring_points_zh", []) or []):
            yield f"feynman.questions[{qi}].scoring_points_zh[{si2}]", sp
    for bi, b in enumerate(fey.get("blind_spots_zh", []) or []):
        yield f"feynman.blind_spots_zh[{bi}]", b


def body_pages(note: dict[str, Any]) -> set[int]:
    """正文(小节)实际讲到的页 —— 覆盖度只看这个,不把测验算进去。"""
    pages: set[int] = set()
    for sec in note.get("sections", []):
        for pt in sec.get("points", []):
            pages.update(int(p) for p in pt.get("also_pages", []) or [])
        pages.update(int(p) for p in sec.get("pages", []) or [])
        for pt in sec.get("points", []):
            if pt.get("page"):
                pages.add(int(pt["page"]))
        for cb in sec.get("configs", []) or []:
            if cb.get("page"):
                pages.add(int(cb["page"]))
        for tb in sec.get("tables", []) or []:
            if tb.get("page"):
                pages.add(int(tb["page"]))
        for v in sec.get("visuals", []) or []:
            pages.update(int(p) for p in v.get("source_pages", []) or [])
    return pages


def quiz_pages(note: dict[str, Any]) -> set[int]:
    """费曼部分引用的页 —— 不计入覆盖度,但受"不超纲"约束(X011)。"""
    pages: set[int] = set()
    fey = note.get("feynman", {}) or {}
    for key in ("questions", "must_master", "difficulties"):
        for item in fey.get(key, []) or []:
            pages.update(int(p) for p in item.get("source_pages", []) or [])
    return pages


def cited_pages(note: dict[str, Any]) -> set[int]:
    return body_pages(note) | quiz_pages(note)


# ------------------------------------------------------------------ 各组检查

def _check_schema(note: dict[str, Any], rep: Report) -> bool:
    try:
        import jsonschema
    except ImportError:
        rep.warn("S000", "schema", "未安装 jsonschema,跳过结构校验",
                 "pip install jsonschema")
        return True
    schema = read_json(SCHEMA_PATH)
    validator = jsonschema.Draft7Validator(schema)
    errs = sorted(validator.iter_errors(note), key=lambda e: list(e.path))
    for e in errs[:40]:
        loc = "/".join(str(x) for x in e.path) or "(根)"
        rep.err("S001", loc, f"结构不符合 schema: {e.message}",
                "对照 note.schema.json / note.template.json 修正字段")
    return not errs


def _check_ids(note: dict[str, Any], rep: Report) -> None:
    seen_sec: set[str] = set()
    seen_vis: set[str] = set()
    for sec in note.get("sections", []):
        sid = sec.get("id", "")
        if sid in seen_sec:
            rep.err("S002", f"sections({sid})", f"小节 id 重复: {sid}", "改成唯一 id")
        seen_sec.add(sid)
        for v in sec.get("visuals", []) or []:
            vid = v.get("id", "")
            if vid in seen_vis:
                rep.err("S003", f"visuals({vid})", f"可视化 id 重复: {vid}", "改成全篇唯一 id")
            seen_vis.add(vid)
    seen_q: set[str] = set()
    for q in (note.get("feynman", {}) or {}).get("questions", []) or []:
        qid = q.get("id", "")
        if qid in seen_q:
            rep.err("S004", f"questions({qid})", f"题目 id 重复: {qid}", "改成唯一 id")
        seen_q.add(qid)


def _check_pages(note: dict[str, Any], index: SourceIndex, rep: Report) -> None:
    total = index.pages_total
    for page in sorted(cited_pages(note)):
        if page < 1 or page > total:
            rep.err("P001", f"page={page}", f"引用页码超出范围(本章共 {total} 页)",
                    "对照 source-text.md 的 [[p.N]] 修正页码")


def _check_quotes(note: dict[str, Any], index: SourceIndex, cfg: Config, rep: Report) -> None:
    th = int(cfg["quote_match_threshold"])
    checked = matched = 0

    def one(where: str, quote: str, pages: list[int], threshold: int, code: str) -> None:
        nonlocal checked, matched
        checked += 1
        score, hit = index.quote_score(quote, pages)
        if score >= threshold:
            matched += 1
            return
        wide, wide_page = index.quote_score(quote, None)
        if wide >= threshold:
            rep.err(code, where,
                    f"引用页码错误:该句相似度在第 {wide_page} 页为 {wide},"
                    f"但你标注的是 {pages}",
                    f"把页码改成 {wide_page}")
        else:
            rep.err(code, where,
                    f"引用与原文不匹配(最高相似度 {max(score, wide)} < {threshold}): "
                    f"“{norm_space(quote)[:90]}”",
                    "回到 source-text.md 逐字复制原文英文句子")

    for si, sec in enumerate(note.get("sections", [])):
        base = f"sections[{si}]({sec.get('id', '?')})"
        if sec.get("heading_en"):
            score, _ = index.quote_score(sec["heading_en"], sec.get("pages"))
            if score < 80:
                rep.warn("Q010", f"{base}.heading_en",
                         f"英文小节标题在原文中匹配度偏低({score})",
                         "改成原文里真实出现的标题或关键短语")
        for pi, pt in enumerate(sec.get("points", [])):
            one(f"{base}.points[{pi}]", pt.get("text_en_quote", ""),
                [int(pt.get("page", 0))], th, "Q001")

    for qi, q in enumerate((note.get("feynman", {}) or {}).get("questions", []) or []):
        one(f"feynman.questions[{qi}]({q.get('id', '?')}).evidence_quote",
            q.get("evidence_quote", ""),
            [int(p) for p in q.get("source_pages", []) or []], th, "Q002")

    fey = note.get("feynman", {}) or {}
    for mi, m in enumerate(fey.get("must_master", []) or []):
        one(f"feynman.must_master[{mi}].evidence_quote", m.get("evidence_quote", ""),
            [int(p) for p in m.get("source_pages", []) or []], th, "Q003")
    for di, d in enumerate(fey.get("difficulties", []) or []):
        one(f"feynman.difficulties[{di}].evidence_quote", d.get("evidence_quote", ""),
            [int(p) for p in d.get("source_pages", []) or []], th, "Q004")

    vth = int(cfg["visual_quote_threshold"])
    for si, sec in enumerate(note.get("sections", [])):
        for vi, v in enumerate(sec.get("visuals", []) or []):
            for gi, g in enumerate(v.get("grounding", []) or []):
                one(f"sections[{si}].visuals[{vi}]({v.get('id', '?')}).grounding[{gi}]",
                    g, [int(p) for p in v.get("source_pages", []) or []], vth, "V001")

    rep.stats["quotes_checked"] = checked
    rep.stats["quotes_matched"] = matched


def _figure_label_vocab(note: dict[str, Any], index: SourceIndex,
                        cfg: Config, rep: Report) -> set[str]:
    """拓扑图里的设备名/网段只存在于图片像素中,不在 PDF 文本层。

    AI 在 figures[].labels_seen 里登记它从图上读到的标签,这些标签即视为合法证据。
    开启 figure_ocr 时会用 OCR 结果核对;未开启时登记项以警告形式列出,便于人工抽查。
    """
    from nlnotes.evidence import SOURCE_TOKEN
    from nlnotes.util import norm_for_match

    def ocr_norm(text: str) -> str:
        """OCR 比对前的归一化。

        小字号的图内文字 OCR 很不可靠:逗号常被认成句点、6 认成 8、l 认成 1,
        更小的标签(如 R1)甚至整个识别不出来。所以比对前先抹平标点差异,
        并且**默认只当警告**,否则正确的标签会被误判成错误、把 AI 卡死。
        """
        t = norm_for_match(text)
        for a, b in ((",", "."), ("，", "."), ("。", "."), (" ", "")):
            t = t.replace(a, b)
        return t

    vocab: set[str] = set()
    declared: list[str] = []
    mismatched: list[str] = []
    as_error = bool(cfg.get("ocr_label_mismatch_as_error"))
    for si, sec in enumerate(note.get("sections", [])):
        for fi, fig in enumerate(sec.get("figures", []) or []):
            fid = fig.get("figure_id", "")
            raw_ocr = index.figure_ocr_text(fid)
            ocr = ocr_norm(raw_ocr)
            # OCR 抽出的图内文字本身就是确定性证据,直接纳入词表 ——
            # 这样图上带大量数值的章节(子网划分、VLAN)不必逐个手工登记
            if raw_ocr and cfg.get("ocr_text_as_evidence", True):
                vocab |= set(SOURCE_TOKEN.findall(norm_for_match(raw_ocr)))
            for li, label in enumerate(fig.get("labels_seen", []) or []):
                norm = norm_for_match(str(label))
                if not norm:
                    continue
                declared.append(str(label))
                vocab |= set(SOURCE_TOKEN.findall(norm))
                if not ocr:
                    continue
                from rapidfuzz import fuzz
                key = ocr_norm(str(label))
                if key in ocr or int(fuzz.partial_ratio(key, ocr)) >= 80:
                    continue
                where = f"sections[{si}].figures[{fi}].labels_seen[{li}]"
                msg = f"标签 “{label}” 在该图的 OCR 结果里找不到"
                fix = ("OCR 对小字号很不可靠(逗号认成句点、R1 这类小标签常整个识别不出),"
                       "所以这条默认只是提醒。确认图上确实没有这段文字再删除它;"
                       "想让它变成硬错误,把 config 的 ocr_label_mismatch_as_error 设为 true")
                if as_error:
                    rep.err("G010", where, msg, fix)
                else:
                    mismatched.append(str(label))
    if mismatched and not as_error:
        rep.warn("G010", "figures.labels_seen",
                 f"有 {len(mismatched)} 个标签在 OCR 结果里没对上(OCR 对小字号不可靠,"
                 f"仅提醒): " + "、".join(mismatched[:10])
                 + (" ..." if len(mismatched) > 10 else ""),
                 "对照图片人工确认即可;确实不存在的标签请删掉")
    if declared and not index.has_ocr:
        rep.warn("G011", "figures.labels_seen",
                 f"共登记了 {len(declared)} 个图内标签,但该章抽取产物里没有 OCR 文本,"
                 f"无法自动核对: " + "、".join(declared[:12])
                 + (" ..." if len(declared) > 12 else ""),
                 "已装 OCR 却仍报这条,按顺序查三件事:"
                 "① config 的 figure_ocr 是否为 true;"
                 "② nlnotes doctor 里「图内文字 OCR」是否显示 ✅ 可用;"
                 "③ 改完是否重跑过 nlnotes extract --force"
                 "(OCR 文本存在抽取产物里,不重跑不会生效)。"
                 "不装 OCR 也可以,人工抽查图片即可")
    return vocab


def _check_tokens(note: dict[str, Any], index: SourceIndex, cfg: Config, rep: Report) -> None:
    if not cfg["token_grounding"]:
        return
    whitelist = set(cfg["token_whitelist"])
    whitelist |= {t.en.lower() for t in load_glossary()}          # 术语表英文本身不算编造
    whitelist |= _figure_label_vocab(note, index, cfg, rep)       # 拓扑图上读到的标签
    total_bad = 0
    for where, text in iter_zh_fields(note):
        if not text:
            continue
        bad = index.ungrounded_tokens(str(text), whitelist)
        if bad:
            total_bad += len(bad)
            rep.err("T001", where,
                    f"出现原文中找不到的技术词/数字: {', '.join(bad[:8])}"
                    + (" ..." if len(bad) > 8 else ""),
                    "删除该内容,或改用原文里真实出现的说法;确属通用词请加入 token_whitelist")
    for i, term in enumerate(note.get("terms", []) or []):
        en = str(term.get("en", ""))
        if en and not index.contains_term(en) and not index.contains_phrase(en, 92):
            rep.err("T002", f"terms[{i}]", f"术语 “{en}” 未在原文中出现",
                    "只登记本章原文真实出现的术语")
    rep.stats["ungrounded_tokens"] = total_bad


def _check_forbidden(note: dict[str, Any], cfg: Config, rep: Report) -> None:
    phrases = [p for p in cfg["forbidden_phrases"] if p]
    for where, text in iter_zh_fields(note):
        for p in phrases:
            if p and p in str(text):
                rep.err("F001", where, f"出现禁用的发散措辞:“{p}”",
                        "删除该表述,只保留原文支持的内容")


def _check_figures(note: dict[str, Any], index: SourceIndex, cfg: Config, rep: Report) -> None:
    used: set[str] = set()
    for si, sec in enumerate(note.get("sections", [])):
        for fi, fig in enumerate(sec.get("figures", []) or []):
            fid = fig.get("figure_id", "")
            if fid not in index.figure_ids:
                rep.err("G001", f"sections[{si}].figures[{fi}]",
                        f"figure_id 不存在: {fid}", "对照 figures.md 选择真实存在的图")
            else:
                used.add(fid)
    fey = note.get("feynman", {}) or {}
    for key in ("questions", "difficulties"):
        for item in fey.get(key, []) or []:
            for fid in item.get("figure_refs", []) or []:
                if fid not in index.figure_ids:
                    rep.err("G002", f"feynman.{key}({item.get('id') or item.get('name_zh')}).figure_refs",
                            f"figure_id 不存在: {fid}", "对照 figures.md")

    available = len(index.figure_ids)
    rep.stats["figures_available"] = available
    rep.stats["figures_used"] = len(used)
    if available and cfg["require_figure_when_available"]:
        need = max(1, int(round(available * float(cfg["min_figure_reference_ratio"]))))
        if len(used) < need:
            rep.err("G003", "figures",
                    f"原文有 {available} 张可用图,笔记只引用了 {len(used)} 张(至少需要 {need} 张)",
                    "把剩余拓扑图补进对应小节的 figures 中并写中文讲解")


def _check_configs(note: dict[str, Any], index: SourceIndex, rep: Report) -> None:
    for si, sec in enumerate(note.get("sections", [])):
        for ci, cb in enumerate(sec.get("configs", []) or []):
            code = str(cb.get("code", ""))
            page = int(cb.get("page", 0))
            score, hit = index.quote_score(code, [page])
            if score < 85:
                wide, wide_page = index.quote_score(code, None)
                if wide >= 85:
                    rep.err("C001", f"sections[{si}].configs[{ci}]",
                            f"配置块页码错误:实际在第 {wide_page} 页", f"页码改成 {wide_page}")
                else:
                    rep.err("C002", f"sections[{si}].configs[{ci}]",
                            f"配置块不是原文逐字内容(相似度 {max(score, wide)})",
                            "从 codeblocks.md / source-text.md 逐字复制")
            for ai, an in enumerate(cb.get("annotations_zh", []) or []):
                line = str(an.get("line", ""))
                if line and line.strip() not in code:
                    rep.err("C003", f"sections[{si}].configs[{ci}].annotations_zh[{ai}]",
                            f"注解引用的行不在该配置块中: “{line[:50]}”",
                            "line 必须是 code 中的原样一行")


def _check_visuals(note: dict[str, Any], rep: Report) -> None:
    count = 0
    ai_count = 0
    for si, sec in enumerate(note.get("sections", [])):
        for vi, v in enumerate(sec.get("visuals", []) or []):
            count += 1
            where = f"sections[{si}].visuals[{vi}]({v.get('id', '?')})"
            kind, spec = v.get("kind"), (v.get("spec") or {})
            if kind == "packet_flow":
                nodes = {n.get("id") for n in spec.get("nodes", []) or []}
                if len(nodes) < 2:
                    rep.err("V010", where, "packet_flow 至少需要 2 个节点", "补充 spec.nodes")
                steps = spec.get("steps") or []
                if not steps:
                    rep.err("V011", where, "packet_flow 缺少 steps", "补充 spec.steps")
                for sti, st in enumerate(steps):
                    for pk in st.get("packets", []) or []:
                        for side in ("from", "to"):
                            if pk.get(side) not in nodes:
                                rep.err("V012", f"{where}.spec.steps[{sti}]",
                                        f"报文的 {side}=“{pk.get(side)}” 不在 nodes 中",
                                        "使用 spec.nodes 里已定义的 id")
                for lk in spec.get("links", []) or []:
                    for side in ("from", "to"):
                        if lk.get(side) not in nodes:
                            rep.err("V013", f"{where}.spec.links",
                                    f"链路的 {side}=“{lk.get(side)}” 不在 nodes 中", "使用已定义的节点 id")
            elif kind == "mermaid" and not str(spec.get("code", "")).strip():
                rep.err("V014", where, "mermaid 缺少 spec.code", "填写 mermaid 源码")
            elif kind == "graphviz" and not str(spec.get("dot", "")).strip():
                rep.err("V015", where, "graphviz 缺少 spec.dot", "填写 DOT 源码")
            elif kind == "comparison_table":
                if not spec.get("headers") or not spec.get("rows"):
                    rep.err("V016", where, "comparison_table 缺少 headers/rows", "补齐表格数据")
            elif kind == "ai_illustration":
                ai_count += 1
                if not str(spec.get("prompt_en", "")).strip():
                    rep.err("V017", where, "ai_illustration 缺少 spec.prompt_en", "补充英文提示词")
    if ai_count > 1:
        rep.warn("V018", "visuals", f"本章使用了 {ai_count} 个 AI 示意图,建议不超过 1 个",
                 "优先用 packet_flow / mermaid / graphviz 等可控图形")
    rep.stats["visuals"] = count


def _check_coverage_and_quiz(note: dict[str, Any], index: SourceIndex,
                             cfg: Config, rep: Report) -> None:
    content = set(index.content_pages) or set(range(1, index.pages_total + 1))
    body = body_pages(note)
    cited = body & content
    ratio = len(cited) / max(1, len(content))
    rep.stats["coverage_ratio"] = round(ratio, 3)
    rep.stats["content_pages"] = len(content)
    rep.stats["cited_pages"] = len(cited)
    if ratio < float(cfg["coverage_min_ratio"]):
        missing = sorted(content - cited)
        rep.err("X001", "coverage",
                f"内容覆盖度 {ratio:.0%} 低于要求 {float(cfg['coverage_min_ratio']):.0%};"
                f"未被引用的正文页: {missing[:25]}{' ...' if len(missing) > 25 else ''}",
                "为这些页补充小节/知识点,或在已有小节中补 points")

    fey = note.get("feynman", {}) or {}
    qs = fey.get("questions", []) or []
    rep.stats["questions"] = len(qs)
    if len(qs) < int(cfg["min_questions"]):
        rep.err("X002", "feynman.questions",
                f"题目数 {len(qs)} 少于要求的 {cfg['min_questions']}", "补充题目")
    if len(qs) > int(cfg["max_questions"]):
        rep.warn("X003", "feynman.questions",
                 f"题目数 {len(qs)} 超过建议上限 {cfg['max_questions']}", "适当精简")

    beyond = sorted(quiz_pages(note) - body)
    if beyond:
        rep.err("X011", "feynman.questions",
                f"题目引用了正文没有讲到的页码 {beyond} —— 这属于超纲",
                "要么在正文补上这些页的知识点,要么把题目改回正文已覆盖的范围")

    types = {q.get("type") for q in qs}
    for need in cfg["required_question_types"]:
        if need not in types:
            rep.err("X004", "feynman.questions", f"缺少必需的题型: {need}",
                    f"至少补一道 type={need} 的题")

    for qi, q in enumerate(qs):
        where = f"feynman.questions[{qi}]({q.get('id', '?')})"
        if not has_cjk(q.get("q_zh", "")):
            rep.err("X005", f"{where}.q_zh", "中文问题里没有中文", "补写中文版问题")
        if not has_cjk(q.get("answer_zh", "")):
            rep.err("X006", f"{where}.answer_zh", "中文答案里没有中文", "补写中文版答案")
        if has_cjk(q.get("q_en", "")):
            rep.err("X007", f"{where}.q_en", "英文问题里混入了中文", "q_en 必须是纯英文")
        if has_cjk(q.get("answer_en", "")):
            rep.err("X008", f"{where}.answer_en", "英文答案里混入了中文", "answer_en 必须是纯英文")

    # 详尽度:知识点密度。太稀说明在做空洞概括,而不是把原文讲透。
    points = sum(len(sec.get("points", [])) for sec in note.get("sections", []))
    density = points / max(1, len(content))
    rep.stats["points_total"] = points
    rep.stats["points_per_content_page"] = round(density, 2)
    need_density = float(cfg["min_points_per_content_page"])
    if density < need_density:
        rep.err("X012", "sections.points",
                f"知识点密度过低:{points} 条 / {len(content)} 个正文页 = {density:.2f},"
                f"低于要求 {need_density};说明笔记在做空洞概括",
                "回到原文逐段补知识点,并用 points[].detail_zh 把机制/前提/例外讲透")

    detailed = sum(1 for sec in note.get("sections", [])
                   for pt in sec.get("points", []) if (pt.get("detail_zh") or "").strip())
    rep.stats["points_with_detail"] = detailed
    if points and detailed / points < 0.25:
        rep.warn("X013", "sections.points.detail_zh",
                 f"只有 {detailed}/{points} 条知识点填了 detail_zh(深入说明)",
                 "对机制性、易混淆的知识点补 detail_zh,笔记才够扎实")

    if len(note.get("sections", [])) < int(cfg["min_sections"]):
        rep.warn("X009", "sections",
                 f"小节数 {len(note.get('sections', []))} 偏少(建议 ≥ {cfg['min_sections']})",
                 "按原文结构再拆细一些")

    if not has_cjk(note.get("title_zh", "")):
        rep.warn("X010", "title_zh", "中文标题看起来不是中文", "补一个中文标题")


def _check_glossary_consistency(note: dict[str, Any], rep: Report) -> None:
    canon = {t.en.lower(): t.zh for t in load_glossary()}
    for i, term in enumerate(note.get("terms", []) or []):
        en, zh = str(term.get("en", "")), str(term.get("zh", ""))
        want = canon.get(en.lower())
        if want and want != zh:
            rep.warn("T003", f"terms[{i}]",
                     f"术语 “{en}” 的译名与术语表不一致:笔记用“{zh}”,术语表为“{want}”",
                     f"统一改为“{want}”,或更新 glossary/terms.csv")


# ------------------------------------------------------------------ 入口

def verify_note(cfg: Config, pdf_id: str, note: dict[str, Any] | None = None) -> Report:
    from nlnotes.taskgen import note_path

    rep = Report(pdf_id)
    index = SourceIndex.load(cfg.extract_dir(pdf_id))
    if note is None:
        p = note_path(cfg, pdf_id)
        if not p.exists():
            rep.err("S000", "note.json", f"未找到 {p}",
                    f"先按 build/tasks/{pdf_id}/TASK.md 产出 note.json")
            return rep
        try:
            note = read_json(p)
        except Exception as exc:
            rep.err("S000", "note.json", f"JSON 解析失败: {exc}", "检查 JSON 语法")
            return rep

    if note.get("pdf_id") and note["pdf_id"] != pdf_id:
        rep.err("S005", "pdf_id", f"pdf_id 不匹配: {note['pdf_id']} != {pdf_id}", "改回正确的 pdf_id")

    structure_ok = _check_schema(note, rep)
    _check_ids(note, rep)
    if structure_ok:
        _check_pages(note, index, rep)
        _check_quotes(note, index, cfg, rep)
        _check_tokens(note, index, cfg, rep)
        _check_forbidden(note, cfg, rep)
        _check_figures(note, index, cfg, rep)
        _check_configs(note, index, rep)
        _check_visuals(note, rep)
        _check_coverage_and_quiz(note, index, cfg, rep)
        _check_glossary_consistency(note, rep)

    out = cfg.report_dir() / f"{pdf_id}.json"
    write_json(out, rep.to_dict())
    level = "ok" if rep.passed else "error"
    log(f"校验 {pdf_id}: {'通过' if rep.passed else '未通过'} — "
        f"{len(rep.errors)} 错误 / {len(rep.warnings)} 警告 -> {out}", level)
    return rep


def format_report(rep: Report) -> str:
    lines = [f"# 校验报告 — {rep.pdf_id}", "",
             f"结果: {'✅ 通过' if rep.passed else '❌ 未通过'}", ""]
    if rep.stats:
        lines += ["## 统计", ""]
        label = {"quotes_checked": "引用校验条数", "quotes_matched": "引用匹配条数",
                 "ungrounded_tokens": "无原文依据的 token 数", "figures_available": "可用图片数",
                 "figures_used": "已引用图片数", "visuals": "自制可视化数",
                 "coverage_ratio": "内容覆盖率", "content_pages": "正文页数",
                 "cited_pages": "已引用页数", "questions": "费曼题目数"}
        for k, v in rep.stats.items():
            lines.append(f"- {label.get(k, k)}: {v}")
        lines.append("")
    for title, items in (("错误(必须修复)", rep.errors), ("警告(建议修复)", rep.warnings)):
        if not items:
            continue
        lines += [f"## {title}", ""]
        for it in items:
            lines.append(f"- `{it['code']}` **{it['where']}** — {it['message']}")
            if it.get("fix"):
                lines.append(f"  - 修复建议: {it['fix']}")
        lines.append("")
    return "\n".join(lines)
