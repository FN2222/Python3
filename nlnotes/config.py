"""流水线配置:默认值 + config/pipeline.json 覆盖 + 命令行覆盖。"""
from __future__ import annotations

import copy
import json
import os
import sys
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
    # 有些课程(尤其概念类,如神经网络、SDN 架构)的图不是位图,而是矩形+箭头画出来的。
    # 这类图 get_images() 抽不到,必须靠"矢量区域渲染"。一张简单的框图可能只有
    # 6~14 个绘图对象,所以阈值不能设太高,否则整类图都会漏掉。
    "extract_vector_figures": True,
    "vector_min_drawings": 6,          # 一页中矢量绘图对象数量达到该值才尝试区域渲染
    "vector_min_cluster_drawings": 4,  # 一张图至少由几个图形对象组成(滤掉分隔线/表格边框)
    "vector_min_cluster_area": 12000,  # 图形区域最小面积(pt²)
    "vector_min_cluster_width_pt": 60.0,   # 图形区域最小宽度
    "vector_min_cluster_height_pt": 40.0,  # 图形区域最小高度
    # 网页导出 PDF 里有三类东西很像图,下面这几项负责挡掉:
    #   页面装饰(搜索框/侧边栏目录框/深色模式按钮)—— 靠"区域内是否含被过滤的导航文字"识别
    #   整页正文(内容外框 + 项目符号)—— 靠长文本行数与占页比例识别
    #   分隔线/表格边框 —— 靠"面积越大要求越多图形对象"识别
    "vector_max_page_ratio": 0.55,         # 图形区域占页面面积的上限
    "vector_max_long_text_lines": 3,       # 区域内长文本行达到该数量即判为正文块
    "vector_area_per_extra_drawing": 40000.0,  # 面积每增加这么多,要求多 1 个图形对象
    "vector_cluster_margin_pt": 16.0,  # 相邻图形合并成一张图的间距容差
    # 矢量图的文字是独立文本对象,只按图形裁剪会把标签切掉(Input 1、Neuron、0 or 1
    # 这些就没了,图也就看不懂了)。下面几项控制"把紧邻的短标签一起框进来",
    # 长句子(正文段落)不会被吸进来。
    "vector_label_gap_pt": 22.0,      # 标签与图形的最大间距
    "vector_label_max_chars": 46,     # 超过这个长度视为正文,不吸纳
    "vector_label_max_grow_pt": 70.0, # 相对原图形区域的最大扩张幅度
    "vector_clip_padding_pt": 10.0,   # 最终裁剪时的留白
    "figure_dedupe": True,            # 同一张图在多页重复出现时只保留第一次
    "caption_lookahead_pt": 90,       # 在图片下方多少 pt 内寻找图注
    "context_chars": 700,             # 图片附近上下文字符数(交给 AI 判断图讲什么)
    # 拓扑图里的设备名/网段通常只存在于图片像素中,不在 PDF 文本层。
    # 开启 OCR 后,这些标签也能进入"原文证据库",笔记描述拓扑图时就不会被误判为臆想。
    # 需要额外安装: pip install pytesseract + 系统安装 tesseract-ocr
    "figure_ocr": False,
    "ocr_lang": "eng",
    # Windows 上 UB-Mannheim 的安装包默认不把 tesseract 加进 PATH,
    # 所以装了也可能找不到。工具会自动探测常见安装位置;
    # 探测不到时在这里写完整路径,例如 C:/Program Files/Tesseract-OCR/tesseract.exe
    "tesseract_cmd": "",
    # OCR 抽出的图内文字本身就是确定性证据,纳入词表后,图上带大量数值的章节
    # (子网划分、VLAN)不必让 AI 逐个手工登记 labels_seen。
    "ocr_text_as_evidence": True,
    # OCR 对小字号很不可靠(逗号认成句点、R1 这类小标签常整个识别不出),
    # 所以"标签在 OCR 里找不到"默认只是警告。设为 true 才升级为硬错误。
    "ocr_label_mismatch_as_error": False,

    # ---------- 网页转 PDF 的噪声清理 ----------
    # NetworkLessons 的 PDF 是从网页导出的,每页会夹带站点导航文字
    # (Search…、Lessons、« »、侧边栏的 Lesson Contents 目录)。
    # 这些噪声会污染原文证据库,还会被字号推断误判成标题(比如 « 被当成一级标题)。
    # 下面这些行会在抽取阶段被丢弃,text.md / 证据库 / 标题识别三处同时生效。
    "clean_text_noise": True,
    "text_noise_lines": [               # 整行完全匹配(忽略大小写与首尾空白)才丢弃
        "search …", "search ...", "search", "lessons", "lesson contents",
        "home", "forum", "members", "sign in", "sign up", "log in", "logout",
        "menu", "table of contents", "share this lesson", "about networklessons",
    ],
    "text_noise_patterns": [            # 正则,匹配即丢弃(用于翻页链接)
        r"^\s*«",                        # « Previous lesson
        r"»\s*$",                        # Next lesson »
        r"^\s*(page\s+)?\d+\s*/\s*\d+\s*$",   # 3 / 14 这类页码
        r"^\s*©\s*\d{4}",                # 版权行
    ],
    # 侧边栏目录:出现 "Lesson Contents" 之后紧跟的编号条目属于目录副本,一并丢弃
    "drop_toc_after_markers": ["lesson contents", "table of contents"],
    "drop_toc_max_lines": 25,

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
    # "详尽扎实"的可度量代理:平均每个正文页至少要有多少条知识点。
    # 低于该密度说明笔记在做空洞概括,而不是真的把原文讲透。
    "min_points_per_content_page": 2.0,
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

    # ---------- 协议级面试复习笔记 ----------
    # 面试题(基础/原理题、场景题、连环追问、避坑)放在整个协议之后,而不是每章之后,
    # 这样跨章素材足够,追问才能有深度。
    # 真实课程库的目录深度往往从 1 层到 6 层不等,固定层级会把面试笔记切得太碎
    # (比如某个叶子目录只有 3 章)。所以默认用 auto:从叶子目录开始向上合并,
    # 直到这一组的章节数达到 group_min_chapters,这样每份面试复习笔记的素材都够。
    # 想手工控制就把 group_mode 改成 "depth",再用 group_depth 指定层数。
    # "selection" —— 按选课清单的每一条包含规则分组。你按协议选课(一次 OSPF、
    #                 一次 BGP),就正好一个协议出一份面试复习笔记,不受目录深度影响。
    #                 **这是"整个 OSPF 后面跟一份面试笔记"这种需求的推荐值。**
    # "auto"      —— 从叶子目录向上合并到至少 group_min_chapters 章
    # "depth"     —— 固定按第 group_depth 层目录
    "group_mode": "auto",               # "selection" | "auto" | "depth"
    "group_min_chapters": 6,            # auto 模式下每组至少要有多少章
    "group_depth": 0,                   # depth 模式:<=0 表示取最后一层目录
    # 分组很大时,chapters.md 会很长。给它一个字符预算,超了就按章均摊裁剪。
    "group_chapters_budget_chars": 90000,
    "interview_quote_threshold": 88,     # grounding 原文比对阈值
    "interview_token_grounding": True,   # 受约束字段仍要回查本协议原文
    "interview_min_must_master": 5,
    "interview_min_fundamentals": 6,
    "interview_min_scenarios": 3,
    "interview_min_followups": 3,
    "interview_min_pitfalls": 5,
    # 生成面试复习笔记时,附给模型的各章原文总字符预算(避免上下文超限)
    "group_source_chars_budget": 120000,

    # ---------- PDF 体检(audit) ----------
    "audit_min_chars_per_page": 120,     # 低于此值判为疑似扫描件/无文本层
    "audit_min_pages": 1,
    "audit_max_garbled_ratio": 0.25,     # 乱码字符占比上限(CID 未映射等)
    "respect_audit_exclusions": True,    # 后续阶段自动跳过 audit 剔除的 PDF

    # ---------- 重复内容 ----------
    # NetworkLessons 把同一节课交叉归档到多个认证方向(CCNA/CCNP/CCIE/R&S),
    # 所以文件总数远大于实际课程数。同一份内容写两遍笔记既浪费额度又没意义,
    # 所以默认只给"正本"写笔记,副本用一篇指向正本的短笔记占位(nlnotes dups)。
    "skip_duplicate_content": True,
    # 交叉归档时文件常被重新导出,字节不同但内容相同。按"标题"识别这类近似重复,
    # 默认只报告不跳过(标题相同也可能确实是不同版本,交由你决定)。
    "report_title_duplicates": True,
    "skip_title_duplicates": False,

    # ---------- 选课清单 ----------
    # 只对清单里列出的课程做笔记,避免每条命令都写一长串 --path。
    # 用 `nlnotes select --init` 按你的课程库生成模板,`--list` 预览命中情况。
    "selection_file": "config/selection.txt",

    # ---------- AI 自动撰写(write) ----------
    # 兼容 OpenAI Chat Completions 协议的任何服务:DeepSeek / 通义 / 智谱 / Kimi /
    # OpenRouter / 本地 vLLM、Ollama 等。留空 base_url 则默认 OpenAI 官方。
    "writer_base_url": "https://api.deepseek.com/v1",
    "writer_model": "deepseek-chat",
    "writer_api_key_env": "NLNOTES_API_KEY",
    "writer_temperature": 0.2,
    "writer_max_tokens": 16000,
    "writer_max_rounds": 4,              # 每章最多"写→校验→修"几轮
    "writer_timeout": 600,
    "writer_retry_on_error": 2,          # 网络/限流错误重试次数
    "writer_sleep_between": 1.0,         # 章节之间的间隔秒数(避免限流)
    "writer_price_in_per_mtok": 0.27,    # 仅用于成本估算(美元/百万 token),按官方定价填
    "writer_price_out_per_mtok": 1.10,

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
            # 只警告、不中断 —— 否则升级版本后配置里留了废弃字段,
            # 连 doctor 都跑不起来,用户没法自查也没法被引导去修。
            print(f"[警告] 配置文件里有 {len(unknown)} 个当前版本不认识的字段,已忽略: "
                  f"{unknown[:8]}{' ...' if len(unknown) > 8 else ''}\n"
                  f"        跑 `python -m nlnotes init --upgrade` 可以清理并补齐新增项。",
                  file=sys.stderr)
        cfg.data.update({k: v for k, v in user.items() if k in DEFAULTS})
        cfg.path = chosen

    for key, env in (("source_root", "NLNOTES_SOURCE_ROOT"),
                     ("notes_dir", "NLNOTES_NOTES_DIR"),
                     ("build_dir", "NLNOTES_BUILD_DIR"),
                     ("writer_base_url", "NLNOTES_WRITER_BASE_URL"),
                     ("writer_model", "NLNOTES_WRITER_MODEL")):
        if os.environ.get(env):
            cfg.data[key] = os.environ[env]

    if overrides:
        cfg.data.update({k: v for k, v in overrides.items() if v is not None})
    return cfg
