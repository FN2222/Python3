"""nlnotes —— 把 NetworkLessons 英文 PDF 课程批量转成"有图有动画有费曼测验"的中文笔记。

设计原则:
1. 原始 PDF 只读,永不写回。
2. 笔记中的每一句结论都必须能回溯到 PDF 的某一页,由 verify 阶段机械校验。
3. AI 只负责产出结构化的 note.json;Markdown、图片、动画由确定性代码渲染。
"""

__version__ = "1.1.2"
