# 示例产出(用合成 PDF 跑出来的真实结果)

这里的内容**不是手写的**,是 `tests/make_sample_pdf.py` 造一份 4 页的合成课程 PDF
(仿 NetworkLessons 排版:正文 + 2 张拓扑图 + 1 段 CLI 输出),
再跑完整条流水线得到的。目的是让你在动手之前先看清最终产出长什么样。

复现方式:

```bash
python tests/run_e2e.py
```

## 目录说明

| 路径 | 内容 |
| --- | --- |
| [`notes/IGP/OSPF/ospf-neighbor-adjacency.md`](notes/IGP/OSPF/ospf-neighbor-adjacency.md) | **最终中文笔记**(建议先看这个) |
| `notes/IGP/OSPF/assets/<pdf_id>/fig-p001-1.png` | 从 PDF 抽出来的原文拓扑图 |
| `notes/IGP/OSPF/assets/<pdf_id>/v1.gif` | 自制动画:hello 报文如何建立邻居关系 |
| `notes/IGP/OSPF/assets/<pdf_id>/v1-steps.png` | 同一张图的**分步静态图**(打印/离线用) |
| `notes/IGP/OSPF/assets/<pdf_id>/v1.mp4` | 同一段动画的 MP4(有 ffmpeg 时自动生成) |
| [`notes/README.md`](notes/README.md) | 自动生成的全局导航索引 |
| [`task-package/TASK.md`](task-package/TASK.md) | 给 AI 的任务指令(阈值是按配置实时算出来的) |
| [`task-package/figures.md`](task-package/figures.md) | 图清单 + 每张图的原文上下文 |
| [`task-package/glossary.md`](task-package/glossary.md) | 本章命中的术语与统一译名 |
| [`task-package/codeblocks.md`](task-package/codeblocks.md) | 原文的 CLI / 配置块 |
| [`task-package/context.json`](task-package/context.json) | 机器可读上下文(页数、图、阈值) |
| [`task-package/note.json`](task-package/note.json) | **AI 该产出的东西**(唯一需要 AI 写的文件) |
| [`task-package/verify-report.json`](task-package/verify-report.json) | 门禁报告(本例 0 错误) |

> `task-package/figures.md` 里的图片预览链接指向 `build/extract/...`,
> 那是运行时目录,没有跟着示例一起提交,所以这里的链接点不开 —— 属正常现象。

## 这个示例展示了什么

看 `ospf-neighbor-adjacency.md` 时,重点关注:

1. **每条知识点后面都跟着原文英文原句和页码** —— 这是可回溯性的体现,
   也是门禁 `Q001` 的检查对象。
2. **原文拓扑图下方有"图中可见标签"** —— 拓扑图里的文字不在 PDF 文本层,
   AI 必须登记它从图上读到的标签,登记过的才允许在中文里使用。
3. **自制图解同时给了 GIF 和分步静态图**,并把"原文依据"折叠在图下方。
4. **mermaid 状态机以代码块内联** —— 因为生成时没装 mermaid-cli,
   自动降级成代码块(Obsidian / Typora / VS Code / GitHub 都能渲染成图)。
5. **CLI 输出逐字保留**,中文解释放在下方表格里,不篡改原文。
6. **费曼测验四步齐全**,题目与答案都是中英双语,答案区折叠,
   每题附原文依据页码与自评要点。
7. **附录声明**:引用通过率、源 PDF 未被修改。

对照 `task-package/verify-report.json` 可以看到这份笔记的统计:
33 条引用全部命中原文、覆盖率 100%、引用了 2/2 张可用拓扑图、8 道费曼题。
