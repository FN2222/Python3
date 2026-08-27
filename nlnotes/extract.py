"""阶段 2 —— 从 PDF 抽取"证据":分页文本、拓扑图/截图、图注、标题层级、配置代码块。

产物(全部落在 build/extract/<pdf_id>/):
    pages.json     每页纯文本 + 是否正文页 + 该页图片 id
    figures.json   图片清单(页码、尺寸、图注推测、周边上下文、相对路径)
    sections.json  标题层级(优先用 PDF 书签,否则按字号推断)
    codeblocks.json 等宽字体聚成的配置/命令块
    text.md        带 [[p.N]] 页标记的全文(交给 AI 阅读)
    figures/*.png|jpg

原始 PDF 以只读方式打开,不做任何写入。
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from pathlib import Path
from typing import Any

try:
    import pymupdf as fitz
except ImportError:      # pymupdf < 1.24 只暴露 fitz
    import fitz

from nlnotes.config import Config
from nlnotes.util import ensure_dir, log, norm_space, write_json, write_text

CAPTION_CUE = re.compile(
    r"^\s*(figure|fig\.?|diagram|topology|table|image|example|picture|图)\s*[\d\-:.]*",
    re.I)
MONO_HINT = re.compile(r"(mono|courier|consol|menlo|inconsolata|dejavusansmono)", re.I)


# --------------------------------------------------------------------------- 文本与结构

def _page_lines(page: "fitz.Page") -> list[dict[str, Any]]:
    """返回该页所有文本行:{text, bbox, size, mono}。"""
    out: list[dict[str, Any]] = []
    data = page.get_text("dict")
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = "".join(s.get("text", "") for s in spans)
            if not text.strip():
                continue
            sizes = [s.get("size", 0) for s in spans if s.get("text", "").strip()]
            fonts = [s.get("font", "") for s in spans]
            out.append({
                "text": text,
                "bbox": list(line.get("bbox", (0, 0, 0, 0))),
                "size": round(max(sizes), 1) if sizes else 0.0,
                "mono": bool(fonts) and all(MONO_HINT.search(f or "") for f in fonts),
            })
    out.sort(key=lambda l: (round(l["bbox"][1], 1), l["bbox"][0]))
    return out


def _body_font_size(all_lines: list[list[dict[str, Any]]]) -> float:
    counter: Counter[float] = Counter()
    for lines in all_lines:
        for ln in lines:
            counter[ln["size"]] += max(1, len(ln["text"]) // 10)
    return counter.most_common(1)[0][0] if counter else 10.0


def _headings_from_font(all_lines: list[list[dict[str, Any]]], body: float) -> list[dict[str, Any]]:
    cands: list[dict[str, Any]] = []
    for pno, lines in enumerate(all_lines, start=1):
        for ln in lines:
            txt = norm_space(ln["text"])
            if not txt or len(txt) > 140 or ln["mono"]:
                continue
            if ln["size"] >= body * 1.12 and not txt.endswith((".", ",", ";")):
                cands.append({"title": txt, "page": pno, "size": ln["size"]})
    if not cands:
        return []
    sizes = sorted({c["size"] for c in cands}, reverse=True)[:4]
    level_of = {s: i + 1 for i, s in enumerate(sizes)}
    return [{"level": level_of.get(c["size"], len(sizes) + 1),
             "title": c["title"], "page": c["page"], "source": "font"}
            for c in cands if c["size"] in level_of]


def _sections(doc: "fitz.Document", all_lines: list[list[dict[str, Any]]],
              body: float) -> list[dict[str, Any]]:
    toc = doc.get_toc(simple=True) or []
    if len(toc) >= 2:
        return [{"level": int(lvl), "title": norm_space(title), "page": int(pg), "source": "toc"}
                for lvl, title, pg in toc if norm_space(title)]
    return _headings_from_font(all_lines, body)


def _codeblocks(all_lines: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """把连续的等宽行聚成配置/命令块(NetworkLessons 的 CLI 输出通常是等宽字体)。"""
    blocks: list[dict[str, Any]] = []
    for pno, lines in enumerate(all_lines, start=1):
        buf: list[str] = []
        for ln in lines:
            if ln["mono"] and ln["text"].strip():
                buf.append(ln["text"].rstrip())
            else:
                if len(buf) >= 2:
                    blocks.append({"page": pno, "lines": len(buf), "code": "\n".join(buf)})
                buf = []
        if len(buf) >= 2:
            blocks.append({"page": pno, "lines": len(buf), "code": "\n".join(buf)})
    return blocks


# --------------------------------------------------------------------------- 图片

def _overlap_x(a: list[float], b: list[float]) -> float:
    left, right = max(a[0], b[0]), min(a[2], b[2])
    width = min(a[2] - a[0], b[2] - b[0]) or 1
    return max(0.0, right - left) / width


def _caption_and_context(lines: list[dict[str, Any]], bbox: list[float],
                         cfg: Config) -> tuple[str, str, str]:
    """返回 (图注推测, 上方最近标题行, 周边上下文)。"""
    below = [ln for ln in lines
             if ln["bbox"][1] >= bbox[3] - 4
             and ln["bbox"][1] - bbox[3] <= cfg["caption_lookahead_pt"]
             and _overlap_x(ln["bbox"], bbox) > 0.15]
    above = [ln for ln in lines if ln["bbox"][3] <= bbox[1] + 4]

    caption = ""
    for ln in below[:4]:
        txt = norm_space(ln["text"])
        if CAPTION_CUE.match(txt):
            caption = txt
            break
    if not caption and below:
        first = norm_space(below[0]["text"])
        if 3 <= len(first) <= 160:
            caption = first

    heading_above = norm_space(above[-1]["text"]) if above else ""
    for ln in reversed(above[-8:]):
        txt = norm_space(ln["text"])
        if 3 <= len(txt) <= 120 and not txt.endswith("."):
            heading_above = txt
            break

    ctx_chars = cfg["context_chars"]
    before = norm_space(" ".join(ln["text"] for ln in above[-14:]))[-ctx_chars // 2:]
    after = norm_space(" ".join(ln["text"] for ln in below[:14]))[:ctx_chars // 2]
    return caption, heading_above, norm_space(f"{before} {after}")


_OCR_STATE: dict[str, Any] = {"checked": False, "available": False}


def _ocr_image(cfg: Config, path: Path) -> str:
    """对拓扑图做 OCR,把图内文字(设备名/接口/网段)纳入证据库。缺少依赖时静默跳过。"""
    if not cfg.get("figure_ocr"):
        return ""
    if not _OCR_STATE["checked"]:
        _OCR_STATE["checked"] = True
        try:
            import pytesseract  # noqa: F401
            from PIL import Image  # noqa: F401
            import shutil as _sh
            _OCR_STATE["available"] = bool(_sh.which("tesseract"))
            if not _OCR_STATE["available"]:
                log("已开启 figure_ocr,但系统未安装 tesseract,OCR 跳过", "warn")
        except ImportError:
            log("已开启 figure_ocr,但未安装 pytesseract,OCR 跳过", "warn")
    if not _OCR_STATE["available"]:
        return ""
    try:
        import pytesseract
        from PIL import Image
        return norm_space(pytesseract.image_to_string(Image.open(path),
                                                      lang=str(cfg.get("ocr_lang", "eng"))))
    except Exception as exc:
        log(f"OCR 失败 {path.name}: {exc}", "warn")
        return ""


def _looks_meaningful(pix: "fitz.Pixmap") -> bool:
    """过滤纯色/近纯色的装饰块。"""
    try:
        sample = pix.samples
        if not sample:
            return False
        step = max(1, len(sample) // 4096)
        vals = sample[::step]
        return len(set(vals)) > 6
    except Exception:
        return True


def _raster_figures(doc: "fitz.Document", page: "fitz.Page", pno: int,
                    lines: list[dict[str, Any]], cfg: Config,
                    out_dir: Path, seen: set[str]) -> list[dict[str, Any]]:
    figs: list[dict[str, Any]] = []
    for idx, info in enumerate(page.get_images(full=True), start=1):
        xref = info[0]
        try:
            raw = doc.extract_image(xref)
        except Exception:
            continue
        data, ext = raw.get("image"), (raw.get("ext") or "png").lower()
        width, height = int(raw.get("width", 0)), int(raw.get("height", 0))
        if not data:
            continue
        if (width < cfg["figure_min_width"] or height < cfg["figure_min_height"]
                or width * height < cfg["figure_min_area"]):
            continue

        digest = hashlib.md5(data).hexdigest()
        if cfg["figure_dedupe"] and digest in seen:
            continue

        try:
            pix = fitz.Pixmap(data)
            if not _looks_meaningful(pix):
                continue
        except Exception:
            pass

        rects = []
        try:
            rects = page.get_image_rects(xref)
        except Exception:
            pass
        bbox = list(rects[0]) if rects else [0.0, 0.0, float(page.rect.width), float(page.rect.height)]

        if ext not in ("png", "jpg", "jpeg", "webp"):
            try:
                pix = fitz.Pixmap(data)
                if pix.n > 4:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                data, ext = pix.tobytes("png"), "png"
            except Exception:
                continue

        fid = f"fig-p{pno:03d}-{idx}"
        fname = f"{fid}.{'jpg' if ext in ('jpg', 'jpeg') else ext}"
        (out_dir / fname).write_bytes(data)
        seen.add(digest)

        caption, heading, ctx = _caption_and_context(lines, bbox, cfg)
        figs.append({
            "figure_id": fid, "file": fname, "page": pno, "kind": "raster",
            "width": width, "height": height, "bbox": [round(v, 1) for v in bbox],
            "caption_guess": caption, "heading_above": heading, "context": ctx,
        })
    return figs


def _cluster_rects(rects: list[fitz.Rect], margin: float = 16.0) -> list[fitz.Rect]:
    boxes = [fitz.Rect(r) for r in rects if r.width > 1 and r.height > 1]
    changed = True
    while changed and boxes:
        changed = False
        merged: list[fitz.Rect] = []
        for box in boxes:
            hit = None
            grown = fitz.Rect(box.x0 - margin, box.y0 - margin, box.x1 + margin, box.y1 + margin)
            for i, m in enumerate(merged):
                if grown.intersects(m):
                    hit = i
                    break
            if hit is None:
                merged.append(fitz.Rect(box))
            else:
                merged[hit] |= box
                changed = True
        boxes = merged
    return boxes


def _vector_figures(page: "fitz.Page", pno: int, lines: list[dict[str, Any]],
                    cfg: Config, out_dir: Path, taken: list[list[float]],
                    seen: set[str]) -> list[dict[str, Any]]:
    """渲染矢量绘制的拓扑图区域(部分 PDF 的拓扑图不是位图)。"""
    try:
        drawings = page.get_drawings()
    except Exception:
        return []
    if len(drawings) < cfg["vector_min_drawings"]:
        return []

    clusters = _cluster_rects([d["rect"] for d in drawings])
    figs: list[dict[str, Any]] = []
    idx = 0
    for cl in sorted(clusters, key=lambda r: (r.y0, r.x0)):
        if cl.get_area() < cfg["vector_min_cluster_area"]:
            continue
        if cl.width < cfg["figure_min_width"] * 0.5 or cl.height < cfg["figure_min_height"] * 0.5:
            continue
        if cl.get_area() > page.rect.get_area() * 0.92:      # 整页边框
            continue
        if any(fitz.Rect(t).intersects(cl) and
               (fitz.Rect(t) & cl).get_area() > cl.get_area() * 0.5 for t in taken):
            continue

        clip = fitz.Rect(cl.x0 - 8, cl.y0 - 8, cl.x1 + 8, cl.y1 + 8) & page.rect
        try:
            pix = page.get_pixmap(matrix=fitz.Matrix(cfg["figure_render_zoom"],
                                                     cfg["figure_render_zoom"]),
                                  clip=clip)
        except Exception:
            continue
        if not _looks_meaningful(pix):
            continue
        data = pix.tobytes("png")
        digest = hashlib.md5(data).hexdigest()
        if cfg["figure_dedupe"] and digest in seen:
            continue
        idx += 1
        fid = f"fig-p{pno:03d}-v{idx}"
        fname = f"{fid}.png"
        (out_dir / fname).write_bytes(data)
        seen.add(digest)
        caption, heading, ctx = _caption_and_context(lines, list(clip), cfg)
        figs.append({
            "figure_id": fid, "file": fname, "page": pno, "kind": "vector",
            "width": pix.width, "height": pix.height,
            "bbox": [round(v, 1) for v in clip],
            "caption_guess": caption, "heading_above": heading, "context": ctx,
        })
    return figs


# --------------------------------------------------------------------------- 主流程

def extract_one(cfg: Config, item: dict[str, Any], force: bool = False) -> dict[str, Any]:
    out_dir = ensure_dir(cfg.extract_dir(item["id"]))
    meta_path = out_dir / "extract.json"
    if meta_path.exists() and not force:
        from nlnotes.util import read_json
        prev = read_json(meta_path)
        if prev.get("sha256") == item.get("sha256"):
            log(f"跳过(已抽取): {item['rel_path']}")
            return prev

    fig_dir = ensure_dir(out_dir / "figures")
    for old in fig_dir.glob("*"):
        old.unlink()

    doc = fitz.open(item["abs_path"])
    try:
        all_lines = [_page_lines(p) for p in doc]
        body_size = _body_font_size(all_lines)

        pages: list[dict[str, Any]] = []
        figures: list[dict[str, Any]] = []
        seen_digests: set[str] = set()

        for pno, page in enumerate(doc, start=1):
            lines = all_lines[pno - 1]
            text = page.get_text("text") or ""
            raster = _raster_figures(doc, page, pno, lines, cfg, fig_dir, seen_digests)
            vector: list[dict[str, Any]] = []
            if cfg["extract_vector_figures"]:
                vector = _vector_figures(page, pno, lines, cfg, fig_dir,
                                         [f["bbox"] for f in raster], seen_digests)
            page_figs = raster + vector
            for f in page_figs:
                f["ocr_text"] = _ocr_image(cfg, fig_dir / f["file"])
            figures.extend(page_figs)
            body_text = norm_space(text)
            pages.append({
                "page": pno,
                "char_count": len(body_text),
                "is_content": len(body_text) >= 150 or bool(page_figs),
                "figure_ids": [f["figure_id"] for f in page_figs],
                "text": text.strip(),
            })

        sections = _sections(doc, all_lines, body_size)
        codeblocks = _codeblocks(all_lines)
        meta = {
            "id": item["id"],
            "rel_path": item["rel_path"],
            "title": item["title"],
            "sha256": item.get("sha256", ""),
            "pages_total": len(pages),
            "content_pages": [p["page"] for p in pages if p["is_content"]],
            "figure_count": len(figures),
            "figure_pages": sorted({f["page"] for f in figures}),
            "codeblock_count": len(codeblocks),
            "body_font_size": body_size,
            "pdf_metadata": {k: v for k, v in (doc.metadata or {}).items()
                             if k in ("title", "author", "creationDate", "producer")},
        }
    finally:
        doc.close()          # 只读打开,从不 save

    write_json(out_dir / "pages.json", {"id": item["id"], "pages": pages})
    write_json(out_dir / "figures.json", {"id": item["id"], "figures": figures})
    write_json(out_dir / "sections.json", {"id": item["id"], "sections": sections})
    write_json(out_dir / "codeblocks.json", {"id": item["id"], "codeblocks": codeblocks})
    write_text(out_dir / "text.md", render_source_text(item, pages))
    write_json(meta_path, meta)

    log(f"抽取完成: {item['rel_path']} — {meta['pages_total']} 页 / "
        f"{meta['figure_count']} 图 / {meta['codeblock_count']} 代码块", "ok")
    return meta


def render_source_text(item: dict[str, Any], pages: list[dict[str, Any]]) -> str:
    """生成带页码标记的原文,供 AI 阅读并引用页码。"""
    lines = [f"# 原文(只读) — {item['title']}",
             "",
             f"- 源文件: `{item['rel_path']}`",
             f"- 总页数: {len(pages)}",
             "",
             "> 每页以 `[[p.N]]` 标记开始。笔记中的所有页码引用必须与此一致。",
             ""]
    for p in pages:
        lines.append(f"\n[[p.{p['page']}]]")
        if p["figure_ids"]:
            lines.append(f"<!-- 本页图片: {', '.join(p['figure_ids'])} -->")
        lines.append(p["text"] or "(本页无可提取文本)")
    return "\n".join(lines) + "\n"


def extract_many(cfg: Config, items: list[dict[str, Any]], force: bool = False) -> list[dict[str, Any]]:
    metas = []
    for it in items:
        try:
            metas.append(extract_one(cfg, it, force=force))
        except Exception as exc:            # 单个 PDF 失败不影响整体批处理
            log(f"抽取失败 {it['rel_path']}: {exc}", "error")
    return metas
