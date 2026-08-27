"""流水线配置:默认值 + config/pipeline.json 覆盖 + 命令行覆盖。"""
from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "pipeline.json"

DEFAULTS: dict[str, Any] = {
    # ---------- 路径 ----------
    # Windows 示例: "D:/NetworkLessons/All-Courses-v3.0"(斜杠或双反斜杠都可)
    "source_root": "D:/NetworkLessons/All-Courses-v3.0",
    "build_dir": "build",            # 中间产物(可随时删除重建)
    "notes_dir": "notes",            # 最终中文笔记输出(镜像 source_root 的目录树)
    "assets_dirname": "assets",      # 每个笔记目录下的图片子目录名

    # ---------- PDF 抽取 ----------
    "figure_min_width": 140,          # 小于该宽度的位图视为图标/装饰,丢弃
    "figure_min_height": 90,
    "figure_min_area": 24000,
    "figure_render_zoom": 2.0,        # 矢量拓扑图区域渲染倍率
    "vector_min_drawings": 12,        # 一页中矢量绘图对象数量达到该值才尝试区域渲染
    "vector_min_cluster_area": 30000,
    "extract_vector_figures": True,
    "figure_dedupe": True,            # 同一张图在多页重复出现时只保留第一次
    "caption_lookahead_pt": 90,       # 在图片下方多少 pt 内寻找图注
    "context_chars": 700,             # 图片附近上下文字符数(交给 AI 判断图讲什么)
    # 拓扑图里的设备名/网段通常只存在于图片像素中,不在 PDF 文本层。
    # 开启 OCR 后,这些标签也能进入"原文证据库",笔记描述拓扑图时就不会被误判为臆想。
    # 需要额外安装: pip install pytesseract + 系统安装 tesseract-ocr
    "figure_ocr": False,
    "ocr_lang": "eng",

    # ---------- 任务包 ----------
    "chunk_chars": 12000,             # 原文过长时的分片大小(便于 AI 分段阅读)
    "task_include_full_text": True,

    # ---------- 质量门禁 ----------
    "quote_match_threshold": 90,      # text_en_quote 与原文页的模糊匹配阈值(0-100)
    "visual_quote_threshold": 88,     # 可视化 grounding 引用阈值
    "coverage_min_ratio": 0.80,       # 被引用的正文页 / 正文总页数
    "min_questions": 8,               # 费曼测验最少题目数
    "max_questions": 20,
    "required_question_types": ["concept", "process"],
    "min_sections": 3,
    "require_figure_when_available": True,   # PDF 有拓扑图时,笔记必须引用
    "min_figure_reference_ratio": 0.6,       # 至少引用可用拓扑图的比例
    "token_grounding": True,           # 技术性 ASCII token 必须出现在原文
    "forbidden_phrases": [
        "据说", "笔者认为", "我认为", "个人觉得", "可能是因为", "推测",
        "一般业界", "众所周知", "扩展阅读", "题外话", "顺便一提",
        "在真实生产环境中通常", "补充一个课外", "超出本章",
    ],
    "token_whitelist": [
        # 允许出现在中文笔记里、但不一定逐字出现在原文的通用词
        "OSI", "TCP/IP", "CLI", "GUI", "ID", "IP", "MAC", "OK", "N/A",
        "Mermaid", "SVG", "PNG", "GIF", "MP4", "AI", "PDF", "Markdown",
        "L2", "L3", "IPv4", "IPv6", "Q", "A",
    ],

    # ---------- 可视化渲染 ----------
    "mermaid_cli": "mmdc",            # 可选;没装就在 Markdown 内联 mermaid 代码块
    "dot_cmd": "dot",                 # 可选;没装就内联 dot 代码块
    "ffmpeg_cmd": "ffmpeg",           # 可选;有则额外输出 mp4
    "anim_frame_ms": 900,             # 动画每帧时长
    "anim_width": 1280,
    "anim_height": 420,          # 最小高度,实际高度按内容自适应
    "anim_substeps": 6,               # 每个逻辑步骤插值出多少动画帧(报文移动更顺滑)
    "steps_grid_cols": 2,             # 分步静态图列数
    "font_candidates": [
        # Windows
        "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc",
        "C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/simsun.ttc",
        # macOS
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        # Linux
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    ],
    "font_path": "",                  # 显式指定中文字体,优先级最高

    # ---------- AI 示意图(可选) ----------
    # provider: "none" | "gemini" | "openai"
    "illustration_provider": "none",
    "gemini_model": "gemini-2.5-flash-image",
    "gemini_api_key_env": "GEMINI_API_KEY",
    "openai_image_model": "gpt-image-1",
    "openai_api_key_env": "OPENAI_API_KEY",
    "illustration_watermark": "AI 辅助示意图 · 非 PDF 原图",
    "illustration_timeout": 120,
}


@dataclass
class Config:
    data: dict[str, Any] = field(default_factory=lambda: copy.deepcopy(DEFAULTS))
    path: Path | None = None

    # --- 便捷访问 ---
    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    @property
    def source_root(self) -> Path:
        return Path(str(self.data["source_root"]).replace("\\", "/")).expanduser()

    @property
    def build_dir(self) -> Path:
        return self._resolve(self.data["build_dir"])

    @property
    def notes_dir(self) -> Path:
        return self._resolve(self.data["notes_dir"])

    def _resolve(self, value: str) -> Path:
        p = Path(str(value).replace("\\", "/")).expanduser()
        return p if p.is_absolute() else (REPO_ROOT / p)

    @property
    def manifest_path(self) -> Path:
        return self.build_dir / "manifest.json"

    @property
    def state_path(self) -> Path:
        return self.build_dir / "state.json"

    def extract_dir(self, pdf_id: str) -> Path:
        return self.build_dir / "extract" / pdf_id

    def task_dir(self, pdf_id: str) -> Path:
        return self.build_dir / "tasks" / pdf_id

    def report_dir(self) -> Path:
        return self.build_dir / "reports"

    def visual_dir(self, pdf_id: str) -> Path:
        return self.build_dir / "visuals" / pdf_id


def load_config(path: str | os.PathLike[str] | None = None,
                overrides: dict[str, Any] | None = None) -> Config:
    """读取配置。查找顺序: 显式 path > config/pipeline.json > 内置默认值。"""
    cfg = Config()
    chosen: Path | None = None
    if path:
        chosen = Path(path)
        if not chosen.exists():
            raise FileNotFoundError(f"配置文件不存在: {chosen}")
    elif DEFAULT_CONFIG_PATH.exists():
        chosen = DEFAULT_CONFIG_PATH

    if chosen is not None:
        user = json.loads(chosen.read_text(encoding="utf-8-sig"))
        unknown = sorted(set(user) - set(DEFAULTS))
        if unknown:
            raise ValueError(f"配置文件包含未知字段: {unknown}(请对照 config/pipeline.example.json)")
        cfg.data.update(user)
        cfg.path = chosen

    for key, env in (("source_root", "NLNOTES_SOURCE_ROOT"),
                     ("notes_dir", "NLNOTES_NOTES_DIR"),
                     ("build_dir", "NLNOTES_BUILD_DIR")):
        if os.environ.get(env):
            cfg.data[key] = os.environ[env]

    if overrides:
        cfg.data.update({k: v for k, v in overrides.items() if v is not None})
    return cfg
