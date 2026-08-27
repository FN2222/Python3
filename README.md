# nlnotes —— NetworkLessons 英文 PDF → 中文学习笔记流水线

把 `D:\NetworkLessons\All-Courses-v3.0` 这类**任意深度嵌套**的英文 PDF 课程目录,
批量做成**有拓扑图、有自制动画、有费曼测验(中英双语)** 的中文笔记,
并用机械门禁保证**不发散、不臆想、严格限定在本章原文之内**。

原始 PDF 全程**只读**,不会被修改或移动。

> - 完整方案文档:**[`docs/00-总体方案.md`](docs/00-总体方案.md)**
> - 想先看产出长什么样:**[`examples/notes/IGP/OSPF/ospf-neighbor-adjacency.md`](examples/notes/IGP/OSPF/ospf-neighbor-adjacency.md)**(含动画 GIF 与分步静态图)

---

## 30 秒了解它怎么工作

```
课程 PDF(只读)
   │ ① scan     递归扫描目录树
   │ ② extract  分页文本 + 拓扑图 + 图注 + CLI 块
   │ ③ tasks    生成自包含"任务包"
   │ ④ AI       ★ 唯一需要 AI 的一步:写结构化 note.json(不写 Markdown)
   │ ⑤ verify   9 组反臆想门禁,不过就不出笔记
   │ ⑥⑦ 渲染    动画 GIF / 分步静态图 / mermaid / 表格 → Markdown
   ▼
notes/<与源目录完全相同的层级>/<课程>.md + assets/
```

**核心设计:AI 只产出受 schema 约束的 JSON,排版与配图由确定性代码渲染。**
内容对不对交给门禁,好不好看交给模板,两者互不干扰。

---

## 快速开始

```powershell
# 1) 装依赖
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2) 生成配置,改成你的课程路径
python -m nlnotes init
#    编辑 config/pipeline.json:
#      "source_root": "D:/NetworkLessons/All-Courses-v3.0"
#      "font_path":   "C:/Windows/Fonts/msyh.ttc"

# 3) 体检
python -m nlnotes doctor

# 4) 准备(先拿 3 章试跑)
python -m nlnotes prepare --path OSPF --limit 3

# 5) 看下一步该写哪章
python -m nlnotes next
```

然后把这句话交给 AI(Cursor / Claude Code / Codex 等):

> 读 `build/tasks/<id>/TASK.md` 并严格按它的要求产出 `build/tasks/<id>/OUTPUT/note.json`。
> `figures.md` 里的每张图都要打开看,把图上的文字登记到 `labels_seen`。
> 写完运行 `python -m nlnotes build --id <id>`,按 `build/reports/<id>.json` 的报告
> 逐条修到通过为止。不要修改门禁配置。

并把 [`prompts/00-system-中文笔记作者.md`](prompts/00-system-中文笔记作者.md) 设为系统提示词。

一键脚本:

```powershell
.\scripts\Run-Pipeline.ps1 -SourceRoot "D:\NetworkLessons\All-Courses-v3.0" -Install
.\scripts\Run-Pipeline.ps1 -BuildOnly     # AI 写完 note.json 后
```

```bash
./scripts/run_pipeline.sh --install --source-root /mnt/d/NetworkLessons/All-Courses-v3.0
./scripts/run_pipeline.sh --build-only
```

---

## 笔记长什么样

每章固定结构:

1. **本章概要** + 边界声明(明确写出覆盖与不覆盖)
2. **术语速查**(中英对照 + 原文页码)
3. **正文精讲** —— 每条知识点都带 `(p.x)` 页码与原文英文原句;
   原文拓扑图 + 中文讲解 + 图中可见标签;
   自制图解(动画 GIF + 分步静态图 + 可折叠的原文依据);
   配置/命令逐字引用 + 逐行中文注解
4. **关键要点回顾**
5. **费曼学习法检验** —— 大白话复述 → 自测题(中英双语)→ 常见盲点 → 复习计划 → 折叠答案(中英双语 + 原文依据 + 自评要点)
6. **附录:可信度说明** —— 引用通过率、AI 图声明、源 PDF 未修改声明

自制动画示例(`packet_flow`,纯 Pillow 自绘,零外部依赖):

- `v1.gif` —— 报文逐步移动的动画
- `v1-steps.png` —— 分步静态图,打印/离线也能看懂
- `v1.mp4` —— 有 ffmpeg 时额外输出

---

## 反臆想门禁(为什么可以信这份笔记)

| 组 | 拦住什么 |
| --- | --- |
| **S** 结构 | 私自加字段、缺字段、题目不够 |
| **P** 页码 | 页码越界 |
| **Q** 原文引用 | 改写原文、编造英文句、页码写错(会告诉你正确页码) |
| **T** token 依据 | 编造协议名 / 定时器数值 / IP / 命令 |
| **F** 发散措辞 | "笔者认为""生产环境通常""众所周知" |
| **G** 图片 | 编图 id、跳过拓扑图、编造图上文字 |
| **C** 配置 | 手打一段"差不多"的 CLI 输出 |
| **V** 可视化 | 画出原文没有的拓扑与流程 |
| **X** 覆盖与测验 | 挑简单段落糊弄、**超纲出题**、中英双语串行 |

两边同时约束:**少写**触发覆盖度不足,**多写**触发无原文依据。

自测(会造合成 PDF 跑完整流水线,并验证 14 个臆想反例都被拦下):

```bash
python tests/run_e2e.py     # 期望输出:✅ 全部自测通过
```

---

## 命令速查

| 命令 | 作用 |
| --- | --- |
| `init` / `doctor` | 生成配置 / 环境体检 |
| `prepare` | `scan` + `extract` + `tasks` 一条龙 |
| `next` | 列出接下来该写哪几章 |
| `build` | 校验 + 渲染 + 组装(**日常用这个**) |
| `verify --show` | 只看门禁报告 |
| `status --detail` / `index` | 查看进度 / 重建导航索引 |

筛选参数:`--id <pdf_id>`(支持前缀)、`--path OSPF`、`--limit 5`。

---

## 目录说明

| 路径 | 内容 |
| --- | --- |
| `nlnotes/` | 流水线代码(scan / extract / taskgen / visuals / verify / assemble) |
| `docs/` | 方案、安装、流水线详解、AI 手册、验收、FAQ |
| `prompts/` | 系统提示词、可视化设计、费曼出题、修订循环 |
| `schemas/note.schema.json` | AI 输出结构定义(`additionalProperties: false`) |
| `templates/note.md.j2` | 笔记排版模板(想改样式改这里) |
| `glossary/terms.csv` | 术语中英对照,可自行扩充 |
| `config/pipeline.example.json` | 全部配置项与默认值 |
| `examples/` | 用合成 PDF 跑出来的真实产出(笔记 + 动画 + 任务包 + 门禁报告) |
| `tests/` | 合成 PDF 生成器 + 端到端自测 |

---

## 依赖

必需:`pymupdf` `Pillow` `Jinja2` `rapidfuzz` `jsonschema`(`pip install -r requirements.txt`)

可选(**缺失自动降级,不影响出笔记**):

| 组件 | 作用 | 缺失时 |
| --- | --- | --- |
| mermaid-cli | mermaid → PNG | 内联 mermaid 代码块 |
| graphviz | DOT → PNG | 内联 dot 代码块 |
| ffmpeg | 额外输出 MP4 | 只出 GIF + 静态图 |
| tesseract + pytesseract | OCR 核对拓扑图标签 | 报告里列出标签供人工抽查 |
| Gemini / OpenAI API Key | 极抽象概念的类比示意图 | 跳过生成,保留提示词 |

---

## 文档

| 文档 | 内容 |
| --- | --- |
| [`docs/00-总体方案.md`](docs/00-总体方案.md) | **完整方案与执行步骤(先看这个)** |
| [`docs/01-环境安装.md`](docs/01-环境安装.md) | 三平台安装、可选组件、OCR 与 AI 图配置 |
| [`docs/02-流水线详解.md`](docs/02-流水线详解.md) | 每阶段输入输出、全部配置项含义 |
| [`docs/03-AI执行手册.md`](docs/03-AI执行手册.md) | AI 逐步操作、各类工具接法、批量调度 |
| [`docs/04-验收与自测.md`](docs/04-验收与自测.md) | 门禁完整清单、自测、人工抽检 |
| [`docs/05-常见问题.md`](docs/05-常见问题.md) | 抽不到图、中文方块、覆盖度过不了等 |
