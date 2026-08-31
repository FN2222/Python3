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
from nlnotes.util import (ensure_dir, log, norm_space, read_bytes, write_bytes,
                          write_json, write_text)

CAPTION_CUE = re.compile(
    r"^\s*(figure|fig\.?|diagram|topology|table|image|example|picture|图)\s*[\d\-:.]*",
    re.I)
MONO_HINT = re.compile(r"(mono|courier|consol|menlo|inconsolata|dejavusansmono)", re.I)


# --------------------------------------------------------------------------- 文本与结构

TOC_ENTRY = re.compile(r"^\s*\d+(\.\d+)*\.?\s+\S")


class NoiseFilter:
    """丢掉网页导出 PDF 夹带的站点导航文字。

    只做整行匹配与少量正则,绝不做子串匹配 —— 否则会误删正文。
    统计丢弃条数,写进抽取产物,便于事后核对是否过度清理。
    """

    def __init__(self, cfg: Config) -> None:
        self.enabled = bool(cfg.get("clean_text_noise", True))
        self.exact = {str(s).strip().lower() for s in cfg.get("text_noise_lines", [])}
        self.patterns = [re.compile(p, re.I) for p in cfg.get("text_noise_patterns", [])]
        self.toc_markers = {str(s).strip().lower() for s in cfg.get("drop_toc_after_markers", [])}
        self.toc_max = int(cfg.get("drop_toc_max_lines", 25))
        self.dropped = 0
        self.dropped_samples: list[str] = []

    def _is_noise_line(self, text: str) -> bool:
        t = norm_space(text)
        if not t:
            return False
        if t.lower() in self.exact:
            return True
        return any(p.search(t) for p in self.patterns)

    def apply(self, lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not self.enabled:
            return lines
        kept: list[dict[str, Any]] = []
        toc_budget = 0
        for ln in lines:
            t = norm_space(ln["text"])
            low = t.lower()

            if toc_budget > 0:
                # 处在"侧边栏目录"区间内:编号条目继续丢,遇到正常句子就结束
                if TOC_ENTRY.match(t) and len(t) < 90 and not t.endswith((".", ":", ";")):
                    toc_budget -= 1
                    self._record(t)
                    continue
                toc_budget = 0

            if self._is_noise_line(t):
                self._record(t)
                if low in self.toc_markers:
                    toc_budget = self.toc_max
                continue
            kept.append(ln)
        return kept

    def _record(self, text: str) -> None:
        self.dropped += 1
        if len(self.dropped_samples) < 12 and text not in self.dropped_samples:
            self.dropped_samples.append(text)

    def stats(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "dropped_lines": self.dropped,
                "samples": self.dropped_samples}


def _page_lines(page: "fitz.Page", noise: NoiseFilter | None = None) -> list[dict[str, Any]]:
    """返回该页所有文本行:{text, bbox, size, mono}(已剔除站点导航噪声)。"""
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
    return noise.apply(out) if noise else out


def _page_text(lines: list[dict[str, Any]]) -> str:
    """由已清理的行重建页面文本 —— 保证 text.md、证据库、标题识别三处口径一致。"""
    return "\n".join(ln["text"].rstrip() for ln in lines).strip()


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
        write_bytes(out_dir / fname, data)
        seen.add(digest)

        caption, heading, ctx = _caption_and_context(lines, bbox, cfg)
        figs.append({
            "figure_id": fid, "file": fname, "page": pno, "kind": "raster",
            "width": width, "height": height, "bbox": [round(v, 1) for v in bbox],
            "caption_guess": caption, "heading_above": heading, "context": ctx,
        })
    return figs


def _cluster_rects(rects: list[fitz.Rect],
                   margin: float = 16.0) -> list[tuple[fitz.Rect, int]]:
    """把邻近的绘图对象聚成一张图,返回 [(外框, 成员数)]。

    注意:**不能丢掉退化成线的矩形**。箭头、连接线的宽或高约等于 0,
    而它们恰恰是把框图各部分连起来的关键 —— 丢了它们,一张图会被切成好几块。
    只过滤掉真正的小点(长宽都 < 2pt)。
    成员数用来区分"真的是图"(很多形状)和"标题下的一条分隔线"(一两个对象)。
    """
    boxes: list[fitz.Rect] = []
    for raw in rects:
        r = fitz.Rect(raw)
        r.normalize()
        if max(r.width, r.height) < 2:
            continue                     # 真正的小点,丢掉
        # PyMuPDF 里宽或高为 0 的矩形是 empty,intersects() 恒为 False,
        # 会导致连接线永远无法把两端合并。所以先把退化的那一维撑开 1pt。
        if r.height < 1:
            r.y1 = r.y0 + 1
        if r.width < 1:
            r.x1 = r.x0 + 1
        boxes.append(r)
    counts = [1] * len(boxes)
    changed = True
    while changed and boxes:
        changed = False
        merged: list[fitz.Rect] = []
        merged_counts: list[int] = []
        for box, cnt in zip(boxes, counts):
            hit = None
            grown = fitz.Rect(box.x0 - margin, box.y0 - margin,
                              box.x1 + margin, box.y1 + margin)
            for i, m in enumerate(merged):
                if grown.intersects(m):
                    hit = i
                    break
            if hit is None:
                merged.append(fitz.Rect(box))
                merged_counts.append(cnt)
            else:
                merged[hit] |= box
                merged_counts[hit] += cnt
                changed = True
        boxes, counts = merged, merged_counts
    return list(zip(boxes, counts))


def _expand_to_labels(box: "fitz.Rect", lines: list[dict[str, Any]],
                      max_gap: float, max_label_len: int,
                      max_grow: float) -> "fitz.Rect":
    """把图形区域扩张到包含紧邻的短文本标签。

    矢量图的文字(Input 1、Neuron、0 or 1、* weight、Total input:)是独立的文本对象,
    不在 drawing 的 bbox 里。只按图形聚类裁剪会把标签切掉,图就看不懂了。
    所以迭代吸纳"距离近且很短"的文本行 —— 长句子(正文段落)不会被吸进来。
    """
    limit = fitz.Rect(box.x0 - max_grow, box.y0 - max_grow,
                      box.x1 + max_grow, box.y1 + max_grow)
    out = fitz.Rect(box)
    for _ in range(6):                      # 迭代几轮让标签链式吸纳,但有硬上限兜底
        changed = False
        grown = fitz.Rect(out.x0 - max_gap, out.y0 - max_gap,
                          out.x1 + max_gap, out.y1 + max_gap)
        for ln in lines:
            text = norm_space(ln["text"])
            if not text or len(text) > max_label_len:
                continue
            r = fitz.Rect(ln["bbox"])
            if out.contains(r) or not grown.intersects(r):
                continue
            merged = fitz.Rect(out) | r
            if not limit.contains(merged):   # 超出允许的扩张范围就不要
                continue
            out = merged
            changed = True
        if not changed:
            break
    return out


def _trim_off_paragraphs(clip: "fitz.Rect", lines: list[dict[str, Any]],
                         max_label_len: int) -> "fitz.Rect":
    """把裁剪框从正文段落处收回来,避免图的边缘蹭到一行正文。

    只在纵向收缩(段落通常是整行宽),而且收缩后高度不得低于原来的 60%,
    否则说明判断有误,宁可不收。
    """
    out = fitz.Rect(clip)
    mid = (out.y0 + out.y1) / 2
    original_h = out.height
    for ln in lines:
        text = norm_space(ln["text"])
        if len(text) <= max_label_len:
            continue                       # 短标签,属于图的一部分
        r = fitz.Rect(ln["bbox"])
        if not out.intersects(r):
            continue
        if r.y0 >= mid:
            out.y1 = min(out.y1, r.y0 - 2)
        else:
            out.y0 = max(out.y0, r.y1 + 2)
    if out.height < original_h * 0.6 or out.is_empty:
        return fitz.Rect(clip)
    return out


def _vector_figures(page: "fitz.Page", pno: int, lines: list[dict[str, Any]],
                    cfg: Config, out_dir: Path, taken: list[list[float]],
                    seen: set[str]) -> list[dict[str, Any]]:
    """渲染矢量绘制的拓扑图区域(部分 PDF 的拓扑图不是位图,而是矩形+箭头画出来的)。"""
    try:
        drawings = page.get_drawings()
    except Exception:
        return []
    if len(drawings) < cfg["vector_min_drawings"]:
        return []

    clusters = _cluster_rects([d["rect"] for d in drawings],
                              margin=float(cfg["vector_cluster_margin_pt"]))
    figs: list[dict[str, Any]] = []
    idx = 0
    for cl, members in sorted(clusters, key=lambda x: (x[0].y0, x[0].x0)):
        # 成员太少的多半是分隔线、表格边框、小装饰,不是图
        if members < int(cfg["vector_min_cluster_drawings"]):
            continue
        if cl.get_area() < cfg["vector_min_cluster_area"]:
            continue
        if cl.width < float(cfg["vector_min_cluster_width_pt"]) or \
                cl.height < float(cfg["vector_min_cluster_height_pt"]):
            continue
        if cl.get_area() > page.rect.get_area() * 0.92:      # 整页边框
            continue
        if any(fitz.Rect(t).intersects(cl) and
               (fitz.Rect(t) & cl).get_area() > cl.get_area() * 0.5 for t in taken):
            continue

        box = _expand_to_labels(cl, lines,
                               max_gap=float(cfg["vector_label_gap_pt"]),
                               max_label_len=int(cfg["vector_label_max_chars"]),
                               max_grow=float(cfg["vector_label_max_grow_pt"]))
        pad = float(cfg["vector_clip_padding_pt"])
        clip = fitz.Rect(box.x0 - pad, box.y0 - pad, box.x1 + pad, box.y1 + pad) & page.rect
        clip = _trim_off_paragraphs(clip, lines, int(cfg["vector_label_max_chars"]))
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
        write_bytes(out_dir / fname, data)
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

    # 用 stream 打开而不是传路径:彻底绕开 Windows 的 MAX_PATH 限制
    doc = fitz.open(stream=read_bytes(item["abs_path"]), filetype="pdf")
    noise = NoiseFilter(cfg)
    try:
        all_lines = [_page_lines(p, noise) for p in doc]
        body_size = _body_font_size(all_lines)

        pages: list[dict[str, Any]] = []
        figures: list[dict[str, Any]] = []
        seen_digests: set[str] = set()

        for pno, page in enumerate(doc, start=1):
            lines = all_lines[pno - 1]
            text = _page_text(lines)
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
            "noise_filter": noise.stats(),
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
