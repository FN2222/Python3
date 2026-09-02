# nlnotes —— NetworkLessons 英文 PDF → 中文学习笔记流水线

把 `D:\NetworkLessons\All-Courses-v3.0` 这类**任意深度嵌套**的英文 PDF 课程目录,
批量做成**有拓扑图、有自制动画、有费曼测验(中英双语)** 的中文笔记,
并用机械门禁保证**不发散、不臆想、严格限定在本章原文之内**。

原始 PDF 全程**只读**,不会被修改或移动。

> - **想直接在本机开始跑(用 Cursor / Grok):[`docs/08-本机上手-用Cursor跑.md`](docs/08-本机上手-用Cursor跑.md)** ← 含可直接复制的提示词
> - 完整方案文档:**[`docs/00-总体方案.md`](docs/00-总体方案.md)**
> - 想先看产出长什么样:**[`examples/notes/IGP/OSPF/ospf-neighbor-adjacency.md`](examples/notes/IGP/OSPF/ospf-neighbor-adjacency.md)**(章节笔记)与 **[`00-面试复习-OSPF.md`](examples/notes/IGP/OSPF/00-面试复习-OSPF.md)**(面试复习笔记)

---

## 30 秒了解它怎么工作

```
课程 PDF(只读)
   │ ① scan / audit   递归扫描 + PDF 体检(扫描件、加密、乱码自动剔除)
   │ ② extract        分页文本 + 拓扑图 + 图注 + CLI 块(可选 OCR 图内文字)
   │ ③ tasks          生成自包含"任务包"
   │ ④ write          ★ 唯一花钱的一步:调模型写结构化 note.json
   │                   写 → 校验 → 错误回灌 → 重写,自动闭环
   │ ⑤ verify         9 组反臆想门禁(本地免费),不过就不出笔记
   │ ⑥⑦ 渲染          动画 GIF / 分步静态图 / mermaid / 表格 → Markdown
   ▼
notes/<与源目录完全相同的层级>/<课程>.md + assets/
   │
   │ ⑧ groups / write-group / build-group
   ▼
notes/<方向>/<协议>/00-面试复习-<协议>.md      ← 协议级面试复习笔记
```

**两种笔记、两套标准:**

| | 章节笔记(每个 PDF 一份) | 协议级面试复习笔记(每个协议一份) |
| --- | --- | --- |
| 发散 | **零发散**,锁死本章原文 | **允许**,但必须分栏 |
| 内容 | 详尽讲解 + 拓扑图 + 自制动画 + 费曼(必须掌握 / 难点 / 自测) | 知识体系图 + 高频原理题(答题模板 + 得分要点)+ 场景题 + 三层连环追问 + 避坑指南 |
| 校验 | 每条知识点带逐字原文 + 页码 | 核心答案带 `grounding` 原文依据;工程经验只能进「🔶 课程外扩展」 |

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

# 4) 体检:确认 PDF 能不能用(扫描件会被剔除并给出处理办法)
python -m nlnotes scan
python -m nlnotes audit          # 看 build/audit.md

# 5) 准备(先拿 3 章试跑)
python -m nlnotes prepare --path OSPF --limit 3
```

### 方式 A:全自动跑完(推荐,不需要人盯着)

```powershell
$env:NLNOTES_API_KEY = "你的key"     # 怎么买、Gemini / Cursor Grok 能不能用:见 docs/05-常见问题.md

python -m nlnotes write --dry-run                # 先估成本,不发请求
python -m nlnotes write --path OSPF --limit 3    # 小批试跑
python -m nlnotes build --path OSPF --limit 3    # 校验 + 渲染,人工看效果
python -m nlnotes write                          # 全量,可中断,重跑自动续上
python -m nlnotes build

python -m nlnotes groups                         # 协议级面试复习笔记
python -m nlnotes write-group
python -m nlnotes build-group

python -m nlnotes cost                           # 看实际花了多少
```

**只有 `write` / `write-group` 花钱,其余全部是本地代码,免费无限跑。**
详见 [`docs/07-批量自动化与成本.md`](docs/07-批量自动化与成本.md)。

### 方式 B:让 Cursor 之类的会话逐章写

```powershell
python -m nlnotes next          # 看下一步该写哪章
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
.\scripts\Update.ps1 -UpgradeConfig       # 更新代码(不依赖 git)
```

```bash
./scripts/run_pipeline.sh --install --source-root /mnt/d/NetworkLessons/All-Courses-v3.0
./scripts/run_pipeline.sh --build-only
```

---

## 笔记长什么样

### A. 章节笔记(每个 PDF 一份)

1. **本章概要** + 边界声明(明确写出覆盖与不覆盖)
2. **术语速查**(中英对照 + 原文页码)
3. **正文精讲** —— 每条知识点都带 `(p.x)` 页码与原文英文原句,
   再加**深入说明**(机制怎么运作 / 成立前提 / 例外情况);
   原文拓扑图 + 中文讲解 + 图中可见标签;
   自制图解(动画 GIF + 分步静态图 + 可折叠的原文依据);
   配置/命令逐字引用 + 逐行中文注解
4. **关键要点回顾**
5. **费曼学习法检验(六步)** —— 大白话复述 → **必须掌握的关键知识点**
   (为什么必须掌握 + 记忆抓手)→ **本章难点**(难在哪 / 为什么容易卡住 / 怎么突破)
   → 自测题(中英双语)→ 常见盲点 → 复习计划 → 折叠答案(中英双语 + 原文依据 + 自评要点)
6. **附录:可信度说明** —— 引用通过率、AI 图声明、源 PDF 未修改声明

### B. 协议级面试复习笔记(每个协议一份,放在整个 OSPF / BGP 之后)

1. **知识体系图** —— mermaid 把各章串成一张图 + 复习顺序及理由
2. **跨章必须掌握清单** —— 面试前必须张口就答的
3. **高频必考基础 / 原理题** —— **高分答题模板**(开场结论 / 分段展开 / 收尾)
   + **得分要点**(面试官逐条打分,中英对照)
4. **场景化面试题** —— 具体到能动手分析的现场 + **解题框架**(排查/推导顺序)
5. **面试官连环追问** —— 每组正好三层:是什么 → 为什么/怎么做 → 边界与代价,
   每层标注"面试官想验证什么"
6. **避坑指南** —— 用候选人原话写出典型错误说法,再说清错在哪、正确怎么说
7. **面试前 5 分钟自查**

题目与答案全部中英双语。课程外的工程经验统一收进
「🔶 课程外扩展」区块,与有原文依据的核心答案分开,一眼可辨。

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
| **X** 覆盖与测验 | 挑简单段落糊弄、**空洞概括**(知识点密度下限)、**超纲出题**、中英双语串行 |

两边同时约束:**少写**触发覆盖度不足,**写浅**触发密度不足,**多写**触发无原文依据。

协议级面试复习笔记另有一套门禁:`grounding` 逐条比对原文、
核心答案 token 依据、三层追问结构、各区块数量下限、不确定表述一律拦下。

自测(造两份合成 PDF 跑完整流水线,用本地假 LLM 验证自动撰写闭环,
并验证 **27 个臆想反例**都被拦下):

```bash
python tests/run_e2e.py     # 期望输出:✅ 全部自测通过
```

---

## 命令速查

| 命令 | 作用 |
| --- | --- |
| `init` / `doctor` | 生成配置 / 环境体检 |
| `audit` | **PDF 体检**:扫描件 / 加密 / 乱码自动剔除,并给出处理办法 |
| `diag` | 把调参需要的信息打包成一个文件(`build/diagnosis.md`),方便求助时分享 |
| `prepare` | `scan` + `extract` + `tasks` 一条龙 |
| `write` | **调模型自动撰写章节笔记**(写→校验→回灌→重写);`--dry-run` 估成本 |
| `build` | 校验 + 渲染 + 组装(**日常用这个**) |
| `groups` / `write-group` / `build-group` | 协议级面试复习笔记:分组 / 撰写 / 校验渲染 |
| `next` | 列出接下来该写哪几章 |
| `verify --show` | 只看门禁报告 |
| `cost` | 汇总 AI 撰写的实际 token 用量与费用 |
| `status --detail` / `index` | 查看进度 / 重建导航索引 |

筛选参数:`--id <pdf_id>`(支持前缀)、`--path OSPF`、`--limit 5`。

---

## 目录说明

| 路径 | 内容 |
| --- | --- |
| `nlnotes/` | 流水线代码(scan / extract / taskgen / visuals / verify / assemble) |
| `docs/` | 方案、安装、流水线详解、AI 手册、验收、FAQ |
| `prompts/` | 系统提示词、可视化设计、费曼出题、修订循环 |
| `schemas/note.schema.json` | 章节笔记的 AI 输出结构(`additionalProperties: false`) |
| `schemas/interview.schema.json` | 协议级面试复习笔记的 AI 输出结构 |
| `templates/note.md.j2` | 章节笔记排版模板(想改样式改这里) |
| `templates/interview.md.j2` | 面试复习笔记排版模板 |
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
| [`docs/07-批量自动化与成本.md`](docs/07-批量自动化与成本.md) | **哪些免费、哪些花钱、怎么全自动跑完、怎么省钱** |
| [`docs/08-本机上手-用Cursor跑.md`](docs/08-本机上手-用Cursor跑.md) | **在本机用 Cursor(Grok)跑:装环境、可复制的提示词、注意点** |
| [`docs/06-会话交接.md`](docs/06-会话交接.md) | 历史决策、踩过的坑、当前进度、如何在新会话继承上下文 |

给 AI 看的入口:[`AGENTS.md`](AGENTS.md)(本地 Agent 与 Cloud Agent 都会自动读取)
与 [`.cursor/rules/nlnotes.mdc`](.cursor/rules/nlnotes.mdc)(`alwaysApply`,注入每个新会话)。
