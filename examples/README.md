# 示例产出(用合成 PDF 跑出来的真实结果)

这里的内容**不是手写的**,是 `tests/make_sample_pdf.py` 造一份 4 页的合成课程 PDF
(仿 NetworkLessons 排版:正文 + 2 张拓扑图 + 1 段 CLI 输出),
再跑完整条流水线得到的。目的是让你在动手之前先看清最终产出长什么样。

复现方式:

```bash
python tests/run_e2e.py
```

## 先看这两份

| 文件 | 是什么 |
| --- | --- |
| [`notes/IGP/OSPF/ospf-neighbor-adjacency.md`](notes/IGP/OSPF/ospf-neighbor-adjacency.md) | **章节笔记**(每个 PDF 一份,零发散) |
| [`notes/IGP/OSPF/00-面试复习-OSPF.md`](notes/IGP/OSPF/00-面试复习-OSPF.md) | **协议级面试复习笔记**(每个协议一份,允许发散但分栏) |

## 目录说明

### 产出

| 路径 | 内容 |
| --- | --- |
| `notes/IGP/OSPF/ospf-neighbor-adjacency.md` | 章节笔记(572 行) |
| `notes/IGP/OSPF/00-面试复习-OSPF.md` | 面试复习笔记(771 行) |
| `notes/IGP/OSPF/assets/<pdf_id>/fig-p001-1.png` | 从 PDF 抽出来的原文拓扑图 |
| `notes/IGP/OSPF/assets/<pdf_id>/v1.gif` | 自制动画:hello 报文如何建立邻居关系 |
| `notes/IGP/OSPF/assets/<pdf_id>/v1-steps.png` | 同一张图的**分步静态图**(打印/离线用) |
| `notes/IGP/OSPF/assets/<pdf_id>/v1.mp4` | 同一段动画的 MP4(有 ffmpeg 时自动生成) |
| [`notes/README.md`](notes/README.md) | 自动生成的全局导航索引 |
| [`audit-report.md`](audit-report.md) | **PDF 体检报告**样例(含"必须剔除"一节与处理办法) |

### 章节笔记的任务包(AI 的输入与输出)

| 路径 | 内容 |
| --- | --- |
| [`task-package/TASK.md`](task-package/TASK.md) | 给 AI 的任务指令(阈值按配置实时算出) |
| [`task-package/figures.md`](task-package/figures.md) | 图清单 + 每张图的原文上下文 |
| [`task-package/glossary.md`](task-package/glossary.md) | 本章命中的术语与统一译名 |
| [`task-package/codeblocks.md`](task-package/codeblocks.md) | 原文的 CLI / 配置块 |
| [`task-package/context.json`](task-package/context.json) | 机器可读上下文(页数、图、阈值) |
| [`task-package/note.json`](task-package/note.json) | **AI 该产出的东西**(唯一需要模型写的文件) |
| [`task-package/verify-report.json`](task-package/verify-report.json) | 门禁报告(本例 0 错误) |

### 面试复习笔记的任务包

| 路径 | 内容 |
| --- | --- |
| [`group-package/TASK.md`](group-package/TASK.md) | 协议级任务指令(身份设定 + 六个区块要求 + **发散边界**) |
| [`group-package/chapters.md`](group-package/chapters.md) | 本协议各章的知识骨架(含 `pdf_id` 与页码,出题素材) |
| [`group-package/context.json`](group-package/context.json) | 机器可读上下文 |
| [`group-package/interview.json`](group-package/interview.json) | **AI 该产出的东西** |
| [`group-package/verify-report.json`](group-package/verify-report.json) | 门禁报告(38/38 条 grounding 通过) |

> `task-package/figures.md` 里的图片预览链接指向 `build/extract/...`,
> 那是运行时目录,没有跟着示例一起提交,所以这里的链接点不开 —— 属正常现象。

## 看章节笔记时,重点关注

1. **每条知识点后面都跟着原文英文原句和页码** —— 可回溯性的体现,也是门禁 `Q001` 的检查对象。
2. **知识点下方的"深入说明"** —— 讲机制怎么运作、成立前提、例外情况。
   这是"详尽扎实、杜绝空洞概括"的落地方式,并且由**知识点密度门禁 `X012`** 保证不偷工
   (本例 16 条知识点 / 4 个正文页 = 4.0,门槛是 2.0)。
3. **原文拓扑图下方的"图中可见标签"** —— 拓扑图里的文字不在 PDF 文本层,
   AI 必须登记它从图上读到的标签,登记过的才允许在中文里使用。
4. **自制图解同时给了 GIF 和分步静态图**,并把"原文依据"折叠在图下方。
5. **mermaid 状态机以代码块内联** —— 生成时没装 mermaid-cli,自动降级成代码块
   (Obsidian / Typora / VS Code / GitHub 都能渲染成图)。
6. **CLI 输出逐字保留**,中文解释放在下方表格里,不篡改原文。
7. **费曼六步**:大白话复述 → **必须掌握清单**(含"为什么必须掌握"与"记忆抓手")
   → **难点分析**(难在哪 / 为什么容易卡住 / 怎么突破 / 对照哪张图)→ 自测题
   → 常见盲点 → 复习计划;答案区折叠,中英双语 + 原文依据 + 自评要点。

## 看面试复习笔记时,重点关注

1. **知识体系图** —— mermaid 把各章串成一张图,并给出复习顺序**和理由**。
2. **高分答题模板** —— 开场先给结论,中间分段(每段有标签),收尾回扣问题。
   面试时可以照着说。
3. **得分要点做成中英对照表** —— 面试官逐条勾,答到几条给几分。
4. **场景题的"解题框架"** —— 场景题真正考的是排查/推导顺序,不是背诵。
5. **连环追问严格三层** —— 是什么 → 为什么/怎么做 → 边界与代价,
   每层都标注"面试官想验证什么"。这是 schema 强制的(`maxItems: 3` + `level` 必须为 1/2/3)。
6. **避坑指南用候选人原话** —— "很多人会这样说……",然后说清错在哪、正确怎么说。
7. **🔶 课程外扩展区块** —— 工程经验被单独隔开并标注"不属于课程内容"。
   这是"允许发散"与"不臆想"的折中方式:发散被允许,但必须承认自己是发散。

## 门禁数据

对照 `task-package/verify-report.json` 与 `group-package/verify-report.json`:

| 指标 | 章节笔记 | 面试复习笔记 |
| --- | --- | --- |
| 原文引用校验 | 42/42 条通过 | 38/38 条 grounding 通过 |
| 内容覆盖率 | 100%(4/4 正文页) | — |
| 知识点密度 | 4.0 条/页(门槛 2.0) | — |
| 拓扑图引用 | 2/2 张 | — |
| 题量 | 9 道自测题 | 6 原理题 + 3 场景题 + 3×3 追问 + 5 避坑 |
| 无原文依据的 token | 0 | 0 |
