from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .models import Diagram, PageContent
from .slug import lesson_slug, safe_filename
from .textutil import normalize_visible_text


def write_lesson(
    page: PageContent,
    save_dir: Path,
    page_index: int,
    diagrams: list[Diagram],
) -> Path:
    """Write one lesson after it has been fully read. Never dumps the whole course."""
    folder = save_dir / lesson_slug(page_index + 1, page.title)
    folder.mkdir(parents=True, exist_ok=True)
    assets = folder / "assets"
    body: list[str] = [
        f"# {page.title}",
        "",
        f"- 来源：{page.final_url or page.source}",
        f"- 阅读顺序：第 {page_index + 1} 页",
        f"- 保存时间：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## 正文",
        "",
        page.text.strip() or "（本页几乎没有可提取的正文）",
        "",
    ]
    if diagrams:
        body.append("## 配图与拓扑图")
        body.append("")
        for diagram in diagrams:
            caption = diagram.caption or diagram.alt or f"图 {diagram.index + 1}"
            if diagram.local_path:
                rel = Path(diagram.local_path)
                try:
                    rel_s = rel.relative_to(folder).as_posix()
                except ValueError:
                    rel_s = rel.as_posix()
                body.append(f"### {caption}")
                body.append("")
                body.append(f"![{caption}]({rel_s})")
                body.append("")
            elif diagram.inline_svg:
                assets.mkdir(parents=True, exist_ok=True)
                svg_name = safe_filename(f"diagram-{diagram.index + 1:02d}", "diagram") + ".svg"
                svg_path = assets / svg_name
                svg_path.write_text(diagram.inline_svg, encoding="utf-8")
                diagram.local_path = str(svg_path)
                body.append(f"### {caption}")
                body.append("")
                body.append(f"![{caption}](assets/{svg_name})")
                body.append("")
            else:
                body.append(f"- {caption}（未保存到本地：{diagram.src}）")
                body.append("")

    lesson_path = folder / "lesson.md"
    lesson_path.write_text("\n".join(body).rstrip() + "\n", encoding="utf-8")
    return lesson_path


def update_index(save_dir: Path, entries: list[dict], stopped: dict | None = None) -> Path:
    save_dir.mkdir(parents=True, exist_ok=True)
    lines = ["# 课程阅读笔记", "", "按真实学习顺序一页一页保存，不是一次导出全部课程。", ""]
    for item in entries:
        title = item.get("title") or item.get("source")
        rel = item.get("path")
        n = item.get("index", 0) + 1
        if rel:
            lines.append(f"{n}. [{title}]({rel})")
        else:
            lines.append(f"{n}. {title}")
    if stopped:
        lines.extend(["", "## 已停止", "", f"- 原因：{stopped.get('reason')}", f"- 说明：{stopped.get('detail')}"])
        if stopped.get("url"):
            lines.append(f"- 停在：{stopped['url']}")
        lines.append("")
        lines.append("请人工处理登录 / 验证码 / 访问限制后再用 `--resume` 继续。不要并发重试。")
    index_path = save_dir / "README.md"
    index_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    state = {
        "entries": entries,
        "stopped": stopped,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    (save_dir / "state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _write_full_book(save_dir, entries)
    return index_path


def _write_full_book(save_dir: Path, entries: list[dict]) -> None:
    parts = ["# 课程全文（按阅读顺序拼接）", "", "本文由已经逐页读完的笔记拼接而成，不是一次批量抓取。", ""]
    for item in entries:
        rel = item.get("path")
        if not rel:
            continue
        lesson = save_dir / rel
        if not lesson.is_file():
            continue
        parts.append(lesson.read_text(encoding="utf-8"))
        parts.append("\n---\n")
    (save_dir / "FULL.md").write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")


def load_state(save_dir: Path) -> dict:
    path = save_dir / "state.json"
    if not path.is_file():
        return {"entries": [], "stopped": None}
    return json.loads(path.read_text(encoding="utf-8"))


def save_asset_bytes(folder: Path, diagram: Diagram, data: bytes, content_type: str | None) -> Path:
    assets = folder / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    ext = _guess_ext(diagram.src, content_type, data)
    name = safe_filename(f"fig-{diagram.index + 1:02d}", "fig") + ext
    path = assets / name
    path.write_bytes(data)
    diagram.local_path = str(path)
    return path


def lesson_folder(save_dir: Path, page: PageContent, page_index: int) -> Path:
    folder = save_dir / lesson_slug(page_index + 1, page.title)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _guess_ext(src: str, content_type: str | None, data: bytes) -> str:
    if content_type:
        ctype = content_type.split(";")[0].strip().lower()
        mapping = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "image/svg+xml": ".svg",
        }
        if ctype in mapping:
            return mapping[ctype]
    lower = src.lower()
    for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"):
        if ext in lower:
            return ".jpg" if ext == ".jpeg" else ext
    if data.startswith(b"\x89PNG"):
        return ".png"
    if data.startswith(b"\xff\xd8"):
        return ".jpg"
    if data[:200].lstrip().startswith(b"<svg") or b"<svg" in data[:400].lower():
        return ".svg"
    return ".bin"


def normalize_note_title(title: str) -> str:
    return normalize_visible_text(title) or "未命名一课"
