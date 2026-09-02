"""证据索引 —— 反臆想门禁的地基。

SourceIndex 把某个 PDF 的原文变成可机械比对的索引:
  * 逐页归一化文本      -> 校验 "text_en_quote" 是不是真的出现在它声明的那一页
  * 全文 token 集合      -> 校验中文笔记里出现的技术性英文/数字有没有原文依据
  * 术语命中表           -> 给 AI 提供本章"允许使用的知识范围"和统一译名
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from rapidfuzz import fuzz

from nlnotes.config import REPO_ROOT
from nlnotes.util import norm_for_match, read_json

GLOSSARY_PATH = REPO_ROOT / "glossary" / "terms.csv"

# 渲染/语法关键字:出现在笔记里属于工具语法,不需要原文依据
SYNTAX_WHITELIST = {
    "graph", "flowchart", "sequencediagram", "subgraph", "end", "lr", "td", "rl", "bt",
    "participant", "note", "over", "left", "right", "digraph", "rankdir", "node",
    "edge", "shape", "label", "style", "fill", "stroke", "classdef", "class",
    "mermaid", "dot", "svg", "png", "gif", "mp4", "md", "json", "yaml",
    "true", "false", "null", "none", "http", "https",
}

TOKEN_IP = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?\b")
TOKEN_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[-_./][A-Za-z0-9]+)*")
TOKEN_NUM = re.compile(r"\b\d{2,}(?:\.\d+)?\b")
SOURCE_TOKEN = re.compile(r"[0-9a-z]+(?:[./_\-][0-9a-z]+)*")


def _word_present(haystack: str, needle: str, case_sensitive: bool = False) -> bool:
    """带词边界的匹配。needle 可能含 . / -,所以用自定义前后界而不是 \\b。"""
    if not needle:
        return False
    flags = 0 if case_sensitive else re.IGNORECASE
    pattern = (r"(?<![0-9A-Za-z])" + re.escape(needle.strip()) + r"(?![0-9A-Za-z])")
    return re.search(pattern, haystack, flags) is not None


@dataclass
class SourceIndex:
    pdf_id: str
    pages_norm: dict[int, str] = field(default_factory=dict)
    full_norm: str = ""
    full_raw: str = ""
    token_set: set[str] = field(default_factory=set)
    pages_total: int = 0
    content_pages: list[int] = field(default_factory=list)
    figure_ids: set[str] = field(default_factory=set)
    figures: list[dict[str, Any]] = field(default_factory=list)
    sections: list[dict[str, Any]] = field(default_factory=list)
    codeblocks: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    # ---------------------------------------------------------------- 加载

    @classmethod
    def load(cls, extract_dir: str | Path) -> "SourceIndex":
        d = Path(extract_dir)
        meta = read_json(d / "extract.json")
        pages = read_json(d / "pages.json")["pages"]
        figures = read_json(d / "figures.json")["figures"]
        sections = read_json(d / "sections.json", {"sections": []})["sections"]
        codeblocks = read_json(d / "codeblocks.json", {"codeblocks": []})["codeblocks"]

        pages_norm = {p["page"]: norm_for_match(p.get("text", "")) for p in pages}
        full_norm = " \n ".join(pages_norm[k] for k in sorted(pages_norm))
        idx = cls(
            pdf_id=meta["id"],
            pages_norm=pages_norm,
            full_norm=full_norm,
            full_raw=" \n ".join((p.get("text") or "") for p in pages),
            token_set=set(SOURCE_TOKEN.findall(full_norm)),
            pages_total=meta["pages_total"],
            content_pages=meta.get("content_pages", []),
            figure_ids={f["figure_id"] for f in figures},
            figures=figures,
            sections=sections,
            codeblocks=codeblocks,
            meta=meta,
        )
        return idx

    # ---------------------------------------------------------------- 引用比对

    def quote_score(self, quote: str, pages: Iterable[int] | None = None) -> tuple[int, int | None]:
        """返回 (最佳相似度 0-100, 命中页码)。pages 为空时在全文范围搜索。"""
        q = norm_for_match(quote)
        if not q:
            return 0, None
        candidates = [p for p in (pages or []) if p in self.pages_norm] or sorted(self.pages_norm)
        best, best_page = 0, None
        for p in candidates:
            text = self.pages_norm[p]
            if not text:
                continue
            score = 100 if q in text else int(fuzz.partial_ratio(q, text))
            if score > best:
                best, best_page = score, p
            if best == 100:
                break
        return best, best_page

    def contains_phrase(self, phrase: str, threshold: int = 90) -> bool:
        q = norm_for_match(phrase)
        if not q:
            return False
        if q in self.full_norm:
            return True
        return int(fuzz.partial_ratio(q, self.full_norm)) >= threshold

    # ---------------------------------------------------------------- token 依据

    def has_token(self, token: str) -> bool:
        t = norm_for_match(token).strip(".,;:!?()[]{}\"'")
        if not t:
            return True
        # 先查 token 集合(精确),再退回子串匹配(容忍单复数、连字符等形态差异)
        return t in self.token_set or t in self.full_norm

    def figure_ocr_text(self, figure_id: str) -> str:
        for f in self.figures:
            if f["figure_id"] == figure_id:
                return f.get("ocr_text", "") or ""
        return ""

    @property
    def has_ocr(self) -> bool:
        return any((f.get("ocr_text") or "").strip() for f in self.figures)

    def contains_term(self, term: str) -> bool:
        """术语存在性判断:短的全大写缩写要求大小写敏感,避免 AS/AD/TE 误命中普通英文单词。"""
        t = term.strip()
        if not t:
            return False
        if len(t) <= 4 and t.isupper():
            return _word_present(self.full_raw, t, case_sensitive=True)
        return _word_present(self.full_norm, t.lower(), case_sensitive=False)

    def ungrounded_tokens(self, text: str, whitelist: set[str]) -> list[str]:
        """挑出中文文本里"没有原文依据"的技术性 ASCII token。"""
        bad: list[str] = []
        seen: set[str] = set()
        wl = {w.lower() for w in whitelist} | SYNTAX_WHITELIST

        for m in TOKEN_IP.finditer(text):
            tok = m.group(0)
            low = tok.lower()
            if low in seen or low in wl:
                continue
            seen.add(low)
            if not self.has_token(tok):
                bad.append(tok)

        stripped = TOKEN_IP.sub(" ", text)
        for m in TOKEN_WORD.finditer(stripped):
            tok = m.group(0)
            low = tok.lower()
            if len(low) < 2 or low in wl or low in seen:
                continue
            seen.add(low)
            if self.has_token(tok):
                continue
            # "DR/BDR"、"2-Way" 这类组合词:拆开后每段都有依据就算通过
            parts = [p for p in re.split(r"[/\\_-]", tok) if p]
            if len(parts) > 1 and all(p.lower() in wl or self.has_token(p) for p in parts):
                continue
            bad.append(tok)

        for m in TOKEN_NUM.finditer(stripped):
            tok = m.group(0)
            if tok in seen:
                continue
            seen.add(tok)
            if not self.has_token(tok):
                bad.append(tok)
        return bad


# ---------------------------------------------------------------------- 术语表

@dataclass
class Term:
    en: str
    zh: str
    category: str = ""
    aliases: list[str] = field(default_factory=list)


def load_glossary(path: str | Path | None = None) -> list[Term]:
    p = Path(path) if path else GLOSSARY_PATH
    if not p.exists():
        return []
    terms: list[Term] = []
    with open(p, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            en = (row.get("en") or "").strip()
            zh = (row.get("zh") or "").strip()
            if not en or not zh:
                continue
            aliases = [a.strip() for a in (row.get("aliases") or "").split("|") if a.strip()]
            if row.get("aliases") and "|" not in row["aliases"]:
                aliases = [row["aliases"].strip()] if row["aliases"].strip() else []
            terms.append(Term(en=en, zh=zh, category=(row.get("category") or "").strip(),
                              aliases=aliases))
    return terms


def glossary_hits(index: SourceIndex, terms: list[Term]) -> list[dict[str, Any]]:
    """找出本章原文实际出现的术语,并附上首次出现的页码。"""
    hits: list[dict[str, Any]] = []
    for term in terms:
        variants = [term.en] + term.aliases
        matched_variant, page = None, None
        for v in variants:
            if not index.contains_term(v):
                continue
            matched_variant = v
            needle = norm_for_match(v)
            for pno in sorted(index.pages_norm):
                if _word_present(index.pages_norm[pno], needle):
                    page = pno
                    break
            break
        if matched_variant:
            hits.append({"en": term.en, "zh": term.zh, "category": term.category,
                         "matched": matched_variant, "first_page": page})
    hits.sort(key=lambda h: (h["first_page"] or 999, h["en"].lower()))
    return hits
