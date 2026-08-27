"""阶段 4 —— 把 AI 给出的"可视化规格"渲染成真正的图片/动画。

支持 5 种 kind:
  mermaid           -> mmdc 渲染 PNG/SVG;没装 mermaid-cli 就在 Markdown 内联代码块(Obsidian/Typora/GitHub 可直接显示)
  graphviz          -> dot 渲染 PNG/SVG;没装 graphviz 就内联代码块
  packet_flow       -> 纯 Pillow 自绘: 动画 GIF + 分步静态图 PNG(+ ffmpeg 可选 MP4),零外部依赖
  comparison_table  -> Markdown 表格
  ai_illustration   -> 可选调用 Gemini(nano banana 系列)/ OpenAI 生成示意图,并自动打上"AI 辅助示意图"水印

packet_flow 是主力:它天生适合表达"报文一步步怎么走"这类抽象过程,而且完全由代码画,
不会凭空编造原文没有的内容(节点、链路、步骤文字全部来自 AI 规格,而规格受 grounding 门禁约束)。
"""
from __future__ import annotations

import base64
import json
import math
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from nlnotes.config import Config
from nlnotes.util import ensure_dir, log, write_json, write_text

# ------------------------------------------------------------------ 配色

PALETTE = {
    "bg": (255, 255, 255),
    "panel": (246, 248, 251),
    "title": (23, 37, 58),
    "text": (44, 56, 74),
    "muted": (120, 132, 150),
    "line": (168, 180, 196),
    "line_hl": (232, 93, 42),
    "packet": (232, 93, 42),
    "packet_text": (255, 255, 255),
    "node_edge": (61, 90, 128),
    "node_fill": (231, 240, 250),
    "node_hl_edge": (232, 93, 42),
    "node_hl_fill": (255, 236, 224),
    "ok": (39, 143, 88),
    "warn": (203, 132, 20),
}

ROLE_SHAPE = {
    "router": "circle", "r": "circle",
    "switch": "rect", "sw": "rect",
    "host": "pc", "pc": "pc", "client": "pc",
    "server": "server", "srv": "server",
    "cloud": "cloud", "internet": "cloud", "wan": "cloud",
    "firewall": "shield", "fw": "shield",
}


# ------------------------------------------------------------------ 字体

_FONT_CACHE: dict[tuple[str, int], Any] = {}


def find_font(cfg: Config) -> str | None:
    if cfg.get("font_path"):
        p = Path(str(cfg["font_path"]).replace("\\", "/"))
        if p.exists():
            return str(p)
        log(f"配置的 font_path 不存在: {p},回退到自动探测", "warn")
    for cand in cfg["font_candidates"]:
        p = Path(cand)
        if p.exists():
            return str(p)
    return None


def load_font(cfg: Config, size: int):
    path = find_font(cfg)
    key = (path or "", size)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    try:
        font = ImageFont.truetype(path, size) if path else ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()
    _FONT_CACHE[key] = font
    return font


def text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    if not text:
        return 0, 0
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def wrap_cjk(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    """中英混排换行:中文按字断行,英文尽量按词断行。"""
    if not text:
        return []
    lines: list[str] = []
    for para in str(text).split("\n"):
        cur = ""
        i = 0
        while i < len(para):
            ch = para[i]
            chunk = ch
            if ch.isascii() and (ch.isalnum() or ch in "-_./:"):
                j = i
                while j < len(para) and para[j].isascii() and (para[j].isalnum() or para[j] in "-_./:"):
                    j += 1
                chunk = para[i:j]
            trial = cur + chunk
            if text_size(draw, trial, font)[0] <= max_width or not cur:
                cur = trial
                i += len(chunk)
            else:
                lines.append(cur)
                cur = ""
        if cur or not lines:
            lines.append(cur)
    return lines


# ------------------------------------------------------------------ 基础绘制

def _arrow(draw: ImageDraw.ImageDraw, p0, p1, color, width=3, head=11):
    draw.line([p0, p1], fill=color, width=width)
    ang = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
    for sign in (1, -1):
        a = ang + sign * math.radians(155)
        draw.line([p1, (p1[0] + head * math.cos(a), p1[1] + head * math.sin(a))],
                  fill=color, width=width)


def _draw_node(draw: ImageDraw.ImageDraw, node: dict[str, Any], pos: tuple[float, float],
               highlighted: bool, font, small_font, radius: int = 34):
    x, y = pos
    edge = PALETTE["node_hl_edge"] if highlighted else PALETTE["node_edge"]
    fill = PALETTE["node_hl_fill"] if highlighted else PALETTE["node_fill"]
    shape = ROLE_SHAPE.get(str(node.get("role", "router")).lower(), "circle")
    w = int(radius * 1.55)

    if shape == "circle":
        draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=fill, outline=edge, width=3)
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            draw.line([(x + dx * 9, y + dy * 9), (x + dx * 20, y + dy * 20)], fill=edge, width=2)
    elif shape == "rect":
        draw.rounded_rectangle([x - w, y - radius * 0.66, x + w, y + radius * 0.66],
                               radius=8, fill=fill, outline=edge, width=3)
        for k in (-1, 0, 1):
            draw.line([(x + k * 18, y - 10), (x + k * 18 + 10, y + 10)], fill=edge, width=2)
    elif shape == "pc":
        draw.rounded_rectangle([x - w, y - radius * 0.8, x + w, y + radius * 0.35],
                               radius=6, fill=fill, outline=edge, width=3)
        draw.rectangle([x - 14, y + radius * 0.35, x + 14, y + radius * 0.62], fill=edge)
        draw.rectangle([x - 26, y + radius * 0.62, x + 26, y + radius * 0.75], fill=edge)
    elif shape == "server":
        draw.rounded_rectangle([x - radius * 0.8, y - radius, x + radius * 0.8, y + radius],
                               radius=6, fill=fill, outline=edge, width=3)
        for k in range(3):
            yy = y - radius + 14 + k * 18
            draw.line([(x - radius * 0.55, yy), (x + radius * 0.55, yy)], fill=edge, width=2)
    elif shape == "cloud":
        draw.ellipse([x - w, y - radius * 0.72, x + w, y + radius * 0.72],
                     fill=fill, outline=edge, width=3)
    else:  # shield
        draw.polygon([(x, y - radius), (x + w * 0.85, y - radius * 0.45),
                      (x + w * 0.6, y + radius * 0.8), (x, y + radius),
                      (x - w * 0.6, y + radius * 0.8), (x - w * 0.85, y - radius * 0.45)],
                     fill=fill, outline=edge)

    label = str(node.get("label", node.get("id", "")))
    for i, line in enumerate(wrap_cjk(draw, label, font, 190)[:2]):
        tw, th = text_size(draw, line, font)
        draw.text((x - tw / 2, y + radius + 6 + i * (th + 4)), line,
                  font=font, fill=PALETTE["title"])
    sub = str(node.get("sublabel", "") or "")
    if sub:
        for i, line in enumerate(wrap_cjk(draw, sub, small_font, 210)[:2]):
            tw, th = text_size(draw, line, small_font)
            draw.text((x - tw / 2, y + radius + 34 + i * (th + 3)), line,
                      font=small_font, fill=PALETTE["muted"])


NODE_RADIUS = 38


def _positions(nodes: list[dict[str, Any]], width: int,
               top: int, content_h: int) -> dict[str, tuple[float, float]]:
    """节点坐标:优先用规格里的相对坐标(0~1);没给就自动均匀布局。

    纵向留出上下边距,避免节点贴边或状态气泡被裁掉。
    """
    pos: dict[str, tuple[float, float]] = {}
    pad_x = 150
    band_top = top + NODE_RADIUS + 34          # 上方要放状态气泡
    band_h = max(1, content_h - (NODE_RADIUS + 34) - (NODE_RADIUS + 52))
    explicit = [n for n in nodes if n.get("x") is not None and n.get("y") is not None]
    auto = [n for n in nodes if n not in explicit]

    ys = sorted({round(float(n["y"]), 3) for n in explicit})
    for n in explicit:
        y_rel = round(float(n["y"]), 3)
        # 只有一行时居中,多行时按相对值铺开
        frac = 0.5 if len(ys) == 1 else (ys.index(y_rel) / max(1, len(ys) - 1))
        pos[n["id"]] = (pad_x + float(n["x"]) * (width - 2 * pad_x),
                        band_top + frac * band_h)
    if auto:
        step = (width - 2 * pad_x) / max(1, len(auto) - 1) if len(auto) > 1 else 0
        y = band_top + band_h * (0.5 if not explicit else 1.0)
        for i, n in enumerate(auto):
            pos[n["id"]] = (pad_x + i * step if len(auto) > 1 else width / 2, y)
    return pos


def _layout(cfg: Config, spec: dict[str, Any], width: int, title: str) -> dict[str, int]:
    """按内容量算画布高度,避免大片空白或文字被裁。"""
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    f_step, f_small = load_font(cfg, 22), load_font(cfg, 16)

    step_lines = 1
    note_lines = 0
    for si, st in enumerate(spec.get("steps") or []):
        label = f"步骤 {si + 1}/{len(spec.get('steps') or [])} · {st.get('title_zh', '')}"
        step_lines = max(step_lines, min(2, len(wrap_cjk(probe, label, f_step, width - 48))))
        if st.get("note_zh"):
            note_lines = max(note_lines,
                             min(3, len(wrap_cjk(probe, str(st["note_zh"]), f_small, width - 60))))

    rows = len({round(float(n["y"]), 3) for n in spec.get("nodes", [])
                if n.get("y") is not None}) or 1
    top = 76 + step_lines * 28 + 26
    content = 150 + 175 * (rows - 1) + (NODE_RADIUS + 34) + (NODE_RADIUS + 52)
    bottom = 30 + note_lines * 24
    height = max(int(cfg["anim_height"]), top + content + bottom)
    content = height - top - bottom
    return {"width": width, "height": height, "top": top, "content": content, "bottom": bottom}


def _shrink(p0: tuple[float, float], p1: tuple[float, float], gap: float = 40.0):
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    d = math.hypot(dx, dy) or 1
    ux, uy = dx / d, dy / d
    return (p0[0] + ux * gap, p0[1] + uy * gap), (p1[0] - ux * gap, p1[1] - uy * gap)


def _render_flow_frame(cfg: Config, spec: dict[str, Any], step_idx: int, t: float,
                       title: str, box: dict[str, int]) -> Image.Image:
    width, height = box["width"], box["height"]
    f_title = load_font(cfg, 30)
    f_step = load_font(cfg, 22)
    f_node = load_font(cfg, 19)
    f_small = load_font(cfg, 16)
    f_pkt = load_font(cfg, 17)

    img = Image.new("RGB", (width, height), PALETTE["bg"])
    d = ImageDraw.Draw(img)

    nodes = spec.get("nodes", [])
    links = spec.get("links", [])
    steps = spec.get("steps", [])
    step = steps[step_idx] if 0 <= step_idx < len(steps) else {}

    # 顶部标题栏
    d.rectangle([0, 0, width, 62], fill=PALETTE["panel"])
    d.line([(0, 62), (width, 62)], fill=PALETTE["line"], width=2)
    for line in wrap_cjk(d, title, f_title, width - 40)[:1]:
        d.text((24, 16), line, font=f_title, fill=PALETTE["title"])

    # 步骤条
    step_title = f"步骤 {step_idx + 1}/{max(1, len(steps))} · {step.get('title_zh', '')}"
    sy = 76
    for i, line in enumerate(wrap_cjk(d, step_title, f_step, width - 48)[:2]):
        d.text((24, sy + i * 28), line, font=f_step, fill=PALETTE["line_hl"])

    note = str(step.get("note_zh", "") or "")
    note_lines = wrap_cjk(d, note, f_small, width - 60)[:3] if note else []
    pos = _positions(nodes, width, box["top"], box["content"])

    hl_nodes = set(step.get("highlight_nodes", []) or [])
    hl_links = {tuple(sorted(pair)) for pair in (step.get("highlight_links", []) or [])
                if isinstance(pair, (list, tuple)) and len(pair) == 2}

    # 链路
    for link in links:
        a, b = link.get("from"), link.get("to")
        if a not in pos or b not in pos:
            continue
        p0, p1 = _shrink(pos[a], pos[b], NODE_RADIUS + 8)
        hot = tuple(sorted((a, b))) in hl_links
        d.line([p0, p1], fill=PALETTE["line_hl"] if hot else PALETTE["line"],
               width=5 if hot else 3)
        lbl = str(link.get("label", "") or "")
        if lbl:
            mx, my = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
            tw, th = text_size(d, lbl, f_small)
            d.rectangle([mx - tw / 2 - 5, my - th - 12, mx + tw / 2 + 5, my - 2],
                        fill=PALETTE["bg"])
            d.text((mx - tw / 2, my - th - 10), lbl, font=f_small, fill=PALETTE["muted"])

    # 节点
    for n in nodes:
        if n["id"] in pos:
            _draw_node(d, n, pos[n["id"]], n["id"] in hl_nodes, f_node, f_small,
                       radius=NODE_RADIUS)

    # 节点状态气泡(如 "Init/2-Way/Full")
    for nid, state in (step.get("state") or {}).items():
        if nid not in pos:
            continue
        x, y = pos[nid]
        txt = str(state)
        tw, th = text_size(d, txt, f_small)
        top_y = y - NODE_RADIUS - 32
        d.rounded_rectangle([x - tw / 2 - 9, top_y, x + tw / 2 + 9, top_y + th + 12],
                            radius=8, fill=(255, 251, 230), outline=PALETTE["warn"], width=2)
        d.text((x - tw / 2, top_y + 5), txt, font=f_small, fill=PALETTE["warn"])

    # 报文
    for pkt in (step.get("packets") or []):
        a, b = pkt.get("from"), pkt.get("to")
        if a not in pos or b not in pos:
            continue
        p0, p1 = _shrink(pos[a], pos[b], NODE_RADIUS + 22)
        cx = p0[0] + (p1[0] - p0[0]) * t
        cy = p0[1] + (p1[1] - p0[1]) * t
        _arrow(d, p0, (cx, cy), PALETTE["packet"], width=4)
        lbl = str(pkt.get("label", "") or "")
        if lbl:
            tw, th = text_size(d, lbl, f_pkt)
            box = [cx - tw / 2 - 10, cy - th / 2 - 8, cx + tw / 2 + 10, cy + th / 2 + 8]
            d.rounded_rectangle(box, radius=9, fill=PALETTE["packet"])
            d.text((cx - tw / 2, cy - th / 2 - 2), lbl, font=f_pkt, fill=PALETTE["packet_text"])

    # 底部说明
    if note_lines:
        y0 = height - (30 + len(note_lines) * 24) + 2
        d.line([(24, y0 - 8), (width - 24, y0 - 8)], fill=PALETTE["line"], width=1)
        for i, line in enumerate(note_lines):
            d.text((24, y0 + i * 24), line, font=f_small, fill=PALETTE["text"])
    return img


def render_packet_flow(cfg: Config, visual: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    spec = visual.get("spec", {})
    steps = spec.get("steps") or []
    if not steps:
        return {"ok": False, "reason": "packet_flow 规格缺少 steps"}

    width = int(cfg["anim_width"])
    subs = max(2, int(cfg["anim_substeps"]))
    title = visual.get("title_zh", "")
    box = _layout(cfg, spec, width, title)

    frames: list[Image.Image] = []
    still: list[Image.Image] = []
    for si in range(len(steps)):
        for k in range(subs):
            t = (k + 1) / subs
            frames.append(_render_flow_frame(cfg, spec, si, t, title, box))
        frames.append(frames[-1].copy())          # 每步末尾停顿一帧
        # 静态图取 0.8,报文停在链路上而不是压住目标节点
        still.append(_render_flow_frame(cfg, spec, si, 0.8, title, box))

    ensure_dir(out_dir)
    gif_path = out_dir / f"{visual['id']}.gif"
    frames[0].save(gif_path, save_all=True, append_images=frames[1:],
                   duration=max(120, int(cfg["anim_frame_ms"]) // subs),
                   loop=0, optimize=True)

    steps_path = out_dir / f"{visual['id']}-steps.png"
    _save_steps_grid(cfg, still, steps_path)

    result = {"ok": True, "animation": gif_path, "still": steps_path, "kind": "packet_flow"}

    ff = shutil.which(str(cfg["ffmpeg_cmd"]))
    if ff:
        frame_dir = ensure_dir(out_dir / f"_frames-{visual['id']}")
        for i, fr in enumerate(frames):
            fr.save(frame_dir / f"{i:04d}.png")
        mp4 = out_dir / f"{visual['id']}.mp4"
        fps = max(1, round(1000 / max(60, int(cfg["anim_frame_ms"]) // subs)))
        proc = subprocess.run(
            [ff, "-y", "-loglevel", "error", "-framerate", str(fps),
             "-i", str(frame_dir / "%04d.png"),
             "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-pix_fmt", "yuv420p", str(mp4)],
            capture_output=True, text=True)
        shutil.rmtree(frame_dir, ignore_errors=True)
        if proc.returncode == 0:
            result["video"] = mp4
        else:
            log(f"ffmpeg 生成 MP4 失败(不影响 GIF): {proc.stderr.strip()[:200]}", "warn")
    return result


def _save_steps_grid(cfg: Config, stills: list[Image.Image], path: Path) -> None:
    """把每步的静态图拼成一张"分步静态图",保证任何 Markdown 阅读器都能看懂过程。"""
    cols = max(1, int(cfg["steps_grid_cols"]))
    scale = 0.62
    tw, th = int(stills[0].width * scale), int(stills[0].height * scale)
    rows = math.ceil(len(stills) / cols)
    gap, pad = 18, 22
    canvas = Image.new("RGB", (pad * 2 + cols * tw + (cols - 1) * gap,
                               pad * 2 + rows * th + (rows - 1) * gap), (236, 240, 245))
    d = ImageDraw.Draw(canvas)
    for i, im in enumerate(stills):
        r, c = divmod(i, cols)
        x = pad + c * (tw + gap)
        y = pad + r * (th + gap)
        canvas.paste(im.resize((tw, th), Image.LANCZOS), (x, y))
        d.rectangle([x, y, x + tw, y + th], outline=PALETTE["line"], width=2)
    canvas.save(path)


# ------------------------------------------------------------------ mermaid / graphviz

def render_mermaid(cfg: Config, visual: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    code = (visual.get("spec", {}) or {}).get("code", "")
    if not code.strip():
        return {"ok": False, "reason": "mermaid 规格缺少 spec.code"}
    exe = shutil.which(str(cfg["mermaid_cli"]))
    if not exe:
        return {"ok": True, "inline": code, "lang": "mermaid", "kind": "mermaid",
                "note": "未安装 mermaid-cli,已内联 mermaid 代码块"}
    ensure_dir(out_dir)
    src = out_dir / f"{visual['id']}.mmd"
    src.write_text(code, encoding="utf-8")
    png = out_dir / f"{visual['id']}.png"
    proc = subprocess.run([exe, "-i", str(src), "-o", str(png), "-b", "white", "-s", "2"],
                          capture_output=True, text=True)
    if proc.returncode != 0 or not png.exists():
        log(f"mmdc 渲染失败,回退内联: {proc.stderr.strip()[:200]}", "warn")
        return {"ok": True, "inline": code, "lang": "mermaid", "kind": "mermaid"}
    return {"ok": True, "still": png, "kind": "mermaid", "source": src}


def render_graphviz(cfg: Config, visual: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    dot = (visual.get("spec", {}) or {}).get("dot", "")
    if not dot.strip():
        return {"ok": False, "reason": "graphviz 规格缺少 spec.dot"}
    exe = shutil.which(str(cfg["dot_cmd"]))
    if not exe:
        return {"ok": True, "inline": dot, "lang": "dot", "kind": "graphviz",
                "note": "未安装 graphviz,已内联 dot 代码块"}
    ensure_dir(out_dir)
    src = out_dir / f"{visual['id']}.dot"
    src.write_text(dot, encoding="utf-8")
    png = out_dir / f"{visual['id']}.png"
    proc = subprocess.run([exe, "-Tpng", "-Gdpi=150", str(src), "-o", str(png)],
                          capture_output=True, text=True)
    if proc.returncode != 0 or not png.exists():
        log(f"dot 渲染失败,回退内联: {proc.stderr.strip()[:200]}", "warn")
        return {"ok": True, "inline": dot, "lang": "dot", "kind": "graphviz"}
    return {"ok": True, "still": png, "kind": "graphviz", "source": src}


# ------------------------------------------------------------------ AI 示意图

def build_illustration_prompt(visual: dict[str, Any]) -> str:
    spec = visual.get("spec", {}) or {}
    labels = spec.get("must_include_labels") or []
    base = spec.get("prompt_en") or visual.get("title_zh", "")
    style = spec.get("style") or ("clean flat vector technical diagram, white background, "
                                  "high contrast, no photorealism, no 3D, no shadows")
    parts = [
        f"Create a single static explanatory diagram for a computer-networking study note: {base}.",
        f"Visual style: {style}.",
        "Requirements: layout must be readable at small size; use simple geometric shapes and arrows.",
    ]
    if labels:
        parts.append("The ONLY text allowed in the image is exactly these labels: "
                     + "; ".join(str(x) for x in labels)
                     + ". Do not invent any other text, numbers, logos or captions.")
    else:
        parts.append("Do not put any text in the image.")
    parts.append("Do not add any protocol, device, value or concept that is not listed above.")
    if spec.get("negative_prompt"):
        parts.append(f"Avoid: {spec['negative_prompt']}.")
    return " ".join(parts)


def _watermark(cfg: Config, path: Path, text: str) -> None:
    try:
        img = Image.open(path).convert("RGB")
    except Exception:
        return
    d = ImageDraw.Draw(img)
    font = load_font(cfg, max(14, img.width // 55))
    tw, th = text_size(d, text, font)
    pad = 8
    d.rectangle([6, img.height - th - 2 * pad - 6, 6 + tw + 2 * pad, img.height - 6],
                fill=(255, 255, 255))
    d.rectangle([6, img.height - th - 2 * pad - 6, 6 + tw + 2 * pad, img.height - 6],
                outline=PALETTE["warn"], width=2)
    d.text((6 + pad, img.height - th - pad - 10), text, font=font, fill=PALETTE["warn"])
    img.save(path)


def render_ai_illustration(cfg: Config, visual: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    provider = str(cfg["illustration_provider"]).lower()
    prompt = build_illustration_prompt(visual)
    ensure_dir(out_dir)
    write_json(out_dir / f"{visual['id']}-prompt.json", {
        "visual_id": visual["id"], "provider": provider, "prompt": prompt,
        "grounding": visual.get("grounding", []), "source_pages": visual.get("source_pages", []),
    })
    if provider == "none":
        return {"ok": True, "skipped": True, "kind": "ai_illustration", "prompt": prompt,
                "note": "illustration_provider=none,已生成提示词但未调用图像模型"}

    try:
        import requests
    except ImportError:
        return {"ok": False, "reason": "缺少 requests 依赖,无法调用图像 API"}

    png = out_dir / f"{visual['id']}.png"
    try:
        if provider == "gemini":
            key = os.environ.get(str(cfg["gemini_api_key_env"]), "")
            if not key:
                return {"ok": True, "skipped": True, "kind": "ai_illustration", "prompt": prompt,
                        "note": f"未设置环境变量 {cfg['gemini_api_key_env']},跳过 AI 示意图"}
            url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
                   f"{cfg['gemini_model']}:generateContent")
            body = {"contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"responseModalities": ["IMAGE"]}}
            resp = requests.post(url, params={"key": key}, json=body,
                                 timeout=int(cfg["illustration_timeout"]))
            if resp.status_code == 400:      # 部分模型版本不接受 responseModalities
                body.pop("generationConfig", None)
                resp = requests.post(url, params={"key": key}, json=body,
                                     timeout=int(cfg["illustration_timeout"]))
            resp.raise_for_status()
            data = resp.json()
            blob = None
            for cand in data.get("candidates", []):
                for part in cand.get("content", {}).get("parts", []):
                    inline = part.get("inlineData") or part.get("inline_data")
                    if inline and inline.get("data"):
                        blob = inline["data"]
                        break
                if blob:
                    break
            if not blob:
                return {"ok": False, "reason": f"Gemini 未返回图片: {json.dumps(data)[:300]}"}
            png.write_bytes(base64.b64decode(blob))
        elif provider == "openai":
            key = os.environ.get(str(cfg["openai_api_key_env"]), "")
            if not key:
                return {"ok": True, "skipped": True, "kind": "ai_illustration", "prompt": prompt,
                        "note": f"未设置环境变量 {cfg['openai_api_key_env']},跳过 AI 示意图"}
            resp = requests.post("https://api.openai.com/v1/images/generations",
                                 headers={"Authorization": f"Bearer {key}"},
                                 json={"model": cfg["openai_image_model"], "prompt": prompt,
                                       "size": "1024x1024", "n": 1},
                                 timeout=int(cfg["illustration_timeout"]))
            resp.raise_for_status()
            item = resp.json()["data"][0]
            if item.get("b64_json"):
                png.write_bytes(base64.b64decode(item["b64_json"]))
            else:
                png.write_bytes(requests.get(item["url"], timeout=60).content)
        else:
            return {"ok": False, "reason": f"未知 illustration_provider: {provider}"}
    except Exception as exc:
        return {"ok": False, "reason": f"图像生成失败: {exc}"}

    _watermark(cfg, png, str(cfg["illustration_watermark"]))
    return {"ok": True, "still": png, "kind": "ai_illustration", "prompt": prompt}


# ------------------------------------------------------------------ 表格 & 调度

def render_comparison_table(visual: dict[str, Any]) -> dict[str, Any]:
    spec = visual.get("spec", {}) or {}
    headers, rows = spec.get("headers") or [], spec.get("rows") or []
    if not headers or not rows:
        return {"ok": False, "reason": "comparison_table 规格缺少 headers/rows"}
    md = ["| " + " | ".join(str(h) for h in headers) + " |",
          "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        cells = [str(c).replace("|", "\\|") for c in row]
        cells += [""] * (len(headers) - len(cells))
        md.append("| " + " | ".join(cells[:len(headers)]) + " |")
    return {"ok": True, "table_md": "\n".join(md), "kind": "comparison_table"}


RENDERERS = {
    "packet_flow": render_packet_flow,
    "mermaid": render_mermaid,
    "graphviz": render_graphviz,
    "ai_illustration": render_ai_illustration,
}


def render_visual(cfg: Config, visual: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    kind = visual.get("kind")
    if kind == "comparison_table":
        return render_comparison_table(visual)
    fn = RENDERERS.get(str(kind))
    if not fn:
        return {"ok": False, "reason": f"不支持的 visual kind: {kind}"}
    try:
        return fn(cfg, visual, out_dir)
    except Exception as exc:
        return {"ok": False, "reason": f"渲染 {visual.get('id')} ({kind}) 失败: {exc}"}


def render_all(cfg: Config, note: dict[str, Any], out_dir: Path) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for sec in note.get("sections", []):
        for visual in sec.get("visuals", []) or []:
            res = render_visual(cfg, visual, out_dir)
            results[visual["id"]] = res
            if not res.get("ok"):
                log(f"可视化失败 {visual['id']}: {res.get('reason')}", "warn")
            elif res.get("note"):
                log(f"可视化 {visual['id']}: {res['note']}")
    if results:
        write_text(out_dir / "render-report.json",
                   json.dumps({k: {kk: (str(vv) if isinstance(vv, Path) else vv)
                                   for kk, vv in v.items()}
                               for k, v in results.items()}, ensure_ascii=False, indent=2))
    return results
