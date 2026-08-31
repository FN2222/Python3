"""PDF 体检 —— 判断哪些 PDF 能用、哪些必须剔除。

回答的问题:"我的 PDF 符合要求吗?能被搜索吗?有问题的踢出来。"

本流水线依赖 **PDF 的文本层**(可搜索文本)。判定分三档:

  ✅ 可用    有文本层、页数正常、文字提取干净
  ⚠️ 需注意  能用但有瑕疵(文字偏少、图偏少、部分页无文本、页数异常多)
  ❌ 剔除    无文本层(扫描件)/ 加密 / 损坏 / 提取出的文字大面积乱码

产物:
    build/audit.json       机器可读结果
    build/audit.md         人看的报告(按方向分组,含剔除原因与处理建议)
    build/excluded.json    被剔除的 pdf_id 清单,后续阶段自动跳过
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

try:
    import pymupdf as fitz
except ImportError:
    import fitz

from nlnotes.config import Config
from nlnotes.scan import load_manifest
from nlnotes.util import log, read_json, write_json, write_text

# CID 未映射、替换符、控制字符 —— 提取出这些说明字体没有可用的 ToUnicode 映射
GARBLED = re.compile(r"[\ufffd\u0000-\u0008\u000b\u000c\u000e-\u001f]|\(cid:\d+\)")
LATIN = re.compile(r"[A-Za-z]")

VERDICT_OK = "ok"
VERDICT_WARN = "warn"
VERDICT_DROP = "drop"


def _analyze(path: Path, cfg: Config) -> dict[str, Any]:
    res: dict[str, Any] = {
        "pages": 0, "chars": 0, "chars_per_page": 0.0, "empty_pages": 0,
        "images": 0, "encrypted": False, "garbled_ratio": 0.0,
        "latin_ratio": 0.0, "verdict": VERDICT_OK, "reasons": [], "hints": [],
    }
    try:
        doc = fitz.open(path)
    except Exception as exc:
        res["verdict"] = VERDICT_DROP
        res["reasons"].append(f"无法打开(文件可能损坏): {exc}")
        res["hints"].append("用 PDF 阅读器确认能否打开;必要时重新下载该课程文件")
        return res

    try:
        if doc.needs_pass or doc.is_encrypted:
            res["encrypted"] = True
            # PyMuPDF 对空密码可自动解密的情况 is_encrypted 也为 True,这里以能否取文本为准
            try:
                _ = doc[0].get_text("text")
            except Exception:
                res["verdict"] = VERDICT_DROP
                res["reasons"].append("PDF 有密码保护,无法读取内容")
                res["hints"].append("用阅读器去掉密码后另存一份(不要覆盖原件)")
                return res

        res["pages"] = doc.page_count
        total_chars = 0
        empty = 0
        garbled = 0
        latin = 0
        images = 0
        for page in doc:
            text = page.get_text("text") or ""
            stripped = text.strip()
            total_chars += len(stripped)
            if len(stripped) < 20:
                empty += 1
            garbled += len(GARBLED.findall(text))
            latin += len(LATIN.findall(text))
            try:
                images += len(page.get_images(full=True))
            except Exception:
                pass

        res["chars"] = total_chars
        res["empty_pages"] = empty
        res["images"] = images
        res["chars_per_page"] = round(total_chars / max(1, doc.page_count), 1)
        res["garbled_ratio"] = round(garbled / max(1, total_chars), 4)
        res["latin_ratio"] = round(latin / max(1, total_chars), 3)
    finally:
        doc.close()

    # ---- 判定 ----
    cpp = res["chars_per_page"]
    if res["pages"] < int(cfg["audit_min_pages"]):
        res["verdict"] = VERDICT_DROP
        res["reasons"].append(f"页数异常({res['pages']} 页)")
    if cpp < float(cfg["audit_min_chars_per_page"]):
        res["verdict"] = VERDICT_DROP
        res["reasons"].append(
            f"几乎没有可提取文字(平均每页 {cpp} 字符 < {cfg['audit_min_chars_per_page']}),"
            f"疑似扫描件或纯图片 PDF")
        res["hints"].append(
            "本流水线依赖 PDF 文本层。请先做 OCR 转成可搜索 PDF"
            "(如 ocrmypdf / Acrobat 的“识别文本”),另存新文件,不要覆盖原件")
    if res["garbled_ratio"] > float(cfg["audit_max_garbled_ratio"]):
        res["verdict"] = VERDICT_DROP
        res["reasons"].append(f"提取出的文字大面积乱码(乱码占比 {res['garbled_ratio']:.1%})")
        res["hints"].append("字体缺少 Unicode 映射。用 Acrobat/其他工具另存或重新导出该 PDF")
    if res["verdict"] != VERDICT_DROP and res["latin_ratio"] < 0.3 and res["chars"] > 0:
        res["verdict"] = VERDICT_WARN
        res["reasons"].append(f"英文字母占比偏低({res['latin_ratio']:.0%}),提取质量可能不佳")

    if res["verdict"] == VERDICT_OK:
        if res["empty_pages"] and res["empty_pages"] / max(1, res["pages"]) > 0.3:
            res["verdict"] = VERDICT_WARN
            res["reasons"].append(
                f"{res['empty_pages']}/{res['pages']} 页几乎没有文字(可能是整页图片)")
            res["hints"].append("这些页的内容抽不到,笔记覆盖度会受影响;可考虑开启 figure_ocr")
        if res["images"] == 0:
            res["verdict"] = VERDICT_WARN
            res["reasons"].append("没有内嵌位图(可能拓扑图是矢量绘制,或本章确实无图)")
            res["hints"].append("矢量图会由 extract_vector_figures 处理;若仍抽不到图,调小 vector_min_drawings")
        if cpp < float(cfg["audit_min_chars_per_page"]) * 3:
            res["verdict"] = VERDICT_WARN
            res["reasons"].append(f"文字偏少(平均每页 {cpp} 字符),内容可能以图为主")

    if res["verdict"] == VERDICT_OK:
        res["reasons"].append("有完整文本层,可正常抽取")
    return res


def audit(cfg: Config, items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    manifest = load_manifest(cfg)
    items = items if items is not None else manifest["items"]

    results: list[dict[str, Any]] = []
    for it in items:
        res = _analyze(Path(it["abs_path"]), cfg)
        results.append({
            "id": it["id"], "rel_path": it["rel_path"], "title": it["title"],
            "course_path_display": it["course_path_display"], **res,
        })

    counts = Counter(r["verdict"] for r in results)
    excluded = [r["id"] for r in results if r["verdict"] == VERDICT_DROP]

    out = {
        "source_root": manifest["source_root"],
        "total": len(results),
        "ok": counts[VERDICT_OK], "warn": counts[VERDICT_WARN], "drop": counts[VERDICT_DROP],
        "excluded_ids": excluded,
        "items": results,
    }
    write_json(cfg.build_dir / "audit.json", out)
    write_json(cfg.build_dir / "excluded.json",
               {"note": "verdict=drop 的 PDF,后续阶段会自动跳过(respect_audit_exclusions)",
                "ids": excluded})
    write_text(cfg.build_dir / "audit.md", format_audit(out))

    log(f"体检完成: 共 {out['total']} 个 — ✅ 可用 {out['ok']} / "
        f"⚠️ 需注意 {out['warn']} / ❌ 剔除 {out['drop']}",
        "ok" if not excluded else "warn")
    log(f"报告: {cfg.build_dir / 'audit.md'}")
    return out


def format_audit(out: dict[str, Any]) -> str:
    badge = {VERDICT_OK: "✅ 可用", VERDICT_WARN: "⚠️ 需注意", VERDICT_DROP: "❌ 剔除"}
    lines = ["# PDF 体检报告", "",
             f"- 课程根目录:`{out['source_root']}`",
             f"- 总数:{out['total']}",
             f"- ✅ 可用:{out['ok']}",
             f"- ⚠️ 需注意:{out['warn']}(能做笔记,但质量可能受影响)",
             f"- ❌ 剔除:{out['drop']}(无法做笔记,后续阶段会自动跳过)", "",
             "> 本流水线依赖 **PDF 的文本层**(即 PDF 里能选中、能搜索的文字)。",
             "> 扫描件(整页是图片)没有文本层,必须先 OCR 成可搜索 PDF 才能用。", ""]

    drops = [r for r in out["items"] if r["verdict"] == VERDICT_DROP]
    if drops:
        lines += ["## ❌ 必须剔除(附原因与处理办法)", "",
                  "| 文件 | 页数 | 每页字符 | 原因 |", "| --- | --- | --- | --- |"]
        for r in drops:
            lines.append(f"| `{r['rel_path']}` | {r['pages']} | {r['chars_per_page']} | "
                         f"{'；'.join(r['reasons'])} |")
        lines += ["", "**处理办法**", ""]
        seen: set[str] = set()
        for r in drops:
            for h in r["hints"]:
                if h not in seen:
                    seen.add(h)
                    lines.append(f"- {h}")
        lines.append("")

    warns = [r for r in out["items"] if r["verdict"] == VERDICT_WARN]
    if warns:
        lines += ["## ⚠️ 需注意(可以做,但先看一眼)", "",
                  "| 文件 | 页数 | 每页字符 | 内嵌图 | 提示 |", "| --- | --- | --- | --- | --- |"]
        for r in warns:
            lines.append(f"| `{r['rel_path']}` | {r['pages']} | {r['chars_per_page']} | "
                         f"{r['images']} | {'；'.join(r['reasons'])} |")
        lines.append("")

    lines += ["## 全部明细", "", "| 判定 | 方向 | 文件 | 页数 | 每页字符 | 内嵌图 | 空白页 |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in sorted(out["items"], key=lambda x: (x["verdict"] != VERDICT_DROP, x["rel_path"])):
        lines.append(f"| {badge[r['verdict']]} | {r['course_path_display']} | "
                     f"`{Path(r['rel_path']).name}` | {r['pages']} | {r['chars_per_page']} | "
                     f"{r['images']} | {r['empty_pages']} |")
    return "\n".join(lines) + "\n"


def excluded_ids(cfg: Config) -> set[str]:
    p = cfg.build_dir / "excluded.json"
    if not p.exists():
        return set()
    try:
        return set(read_json(p).get("ids", []))
    except Exception:
        return set()
