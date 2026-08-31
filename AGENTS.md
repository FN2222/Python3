# AGENTS.md

本文件会被 Cursor 的本地 Agent 与 Cloud Agent **自动读取**。
新会话不需要了解任何历史对话,读完本文件即可正确接手。

## 这个仓库是什么

`nlnotes` —— 一条把 **NetworkLessons 英文 PDF 课程**批量转成**中文学习笔记**的流水线。
笔记要求:知识点配原文拓扑图、抽象处配自制动画/静态图、章末有中英双语费曼测验,
并且**严格限定在本章 PDF 原文之内,不发散、不臆想**。

用户的课程目录在本机 `D:\NetworkLessons\All-Courses-v3.0`(任意深度嵌套,末层是 PDF)。

核心架构(详见 [`docs/00-总体方案.md`](docs/00-总体方案.md)):

```
课程 PDF(只读)
  ① scan     递归扫描目录树           → build/manifest.json
  ② extract  分页文本+拓扑图+CLI 块    → build/extract/<id>/
  ③ tasks    生成自包含任务包          → build/tasks/<id>/
  ④ AI  ★    写 note.json(结构化)     → build/tasks/<id>/OUTPUT/note.json
  ⑤ verify   9 组反臆想门禁            → build/reports/<id>.json
  ⑥⑦ 渲染    动画/图/Markdown          → notes/<镜像源目录>/<课程>.md
```

**最重要的设计取舍:AI 只产出受 JSON Schema 约束的 `note.json`,不写 Markdown。**
排版、配图、动画由确定性代码渲染。这样"内容对不对"由门禁机械保证,
"好不好看"由模板保证,两者解耦。改需求时请保持这个边界。

## 绝对不要做的事

1. **不要修改、移动、重命名用户的原始 PDF。** 全流程只读打开。
2. **不要为了让笔记通过校验而下调门禁阈值**(`quote_match_threshold`、
   `coverage_min_ratio`、`min_questions` 等)。阈值调低等于放弃"不臆想"的保证。
   唯一合理的放宽:往 `token_whitelist` 加与课程无关的通用词(如 `Markdown`、`OSI`);
   协议名、命令、数值一律不许加白名单。
3. **不要手写笔记 Markdown。** 笔记只能由 `nlnotes build` 从 `note.json` 渲染。
4. **不要在 `templates/note.md.j2` 里让内容行以 `{% ... %}` 结尾。**
   模板开了 `trim_blocks`,块标签会吃掉行尾换行,导致 Markdown 表格与列表粘连。
   需要循环拼接时,改用 Jinja 过滤器(`pages_fmt` / `codes`)或在 Python 里拼好再传入。
5. **不要把 `build/`、`notes/`、`config/pipeline.json` 提交进 git**(已在 `.gitignore`)。
   `examples/` 是有意提交的示例产出,不要误删。

## 常用命令

```bash
python -m nlnotes doctor                  # 体检:路径/依赖/中文字体/可选工具
python -m nlnotes prepare --path OSPF --limit 3   # scan+extract+tasks(建议先小批)
python -m nlnotes next                    # 列出接下来该写哪几章
python -m nlnotes build --id <pdf_id>     # 校验+渲染+组装(日常用这个)
python -m nlnotes verify --id <pdf_id> --show
python -m nlnotes status --detail
python tests/run_e2e.py                   # 端到端自测,期望 ✅ 全部自测通过
```

## 接到"写某一章笔记"的任务时

按 [`docs/03-AI执行手册.md`](docs/03-AI执行手册.md) 执行,并遵守
[`prompts/00-system-中文笔记作者.md`](prompts/00-system-中文笔记作者.md) 的全部铁律。
简版流程:

1. 读 `build/tasks/<id>/TASK.md`(阈值是按当前配置实时算出来的,以它为准);
2. 读 `source-text.md`(页码标记 `[[p.N]]`)、`outline.md`、`glossary.md`、`codeblocks.md`;
3. **逐张打开 `figures.md` 里的图片实际看图**,把图上文字登记到 `figures[].labels_seen`
   —— 拓扑图里的 `R1`、`Gi0/1`、`10.0.0.0/24` 不在 PDF 文本层,不登记就会被判为臆想;
4. 写 `OUTPUT/note.json`,每条知识点的 `text_en_quote` 必须从原文**复制粘贴**,不是凭理解写;
5. 跑 `python -m nlnotes build --id <id>`,按 `build/reports/<id>.json` 逐条修;
   错误码到改法的对照表在 [`prompts/40-修订循环.md`](prompts/40-修订循环.md);
6. 最多自动重试 5 轮,仍不通过就停下汇报,不要靠删内容或改阈值过关。

## 改代码时的注意点

| 模块 | 职责 | 改动风险 |
| --- | --- | --- |
| `nlnotes/scan.py` | 扫描、`pdf_id` 生成、输出路径镜像 | `pdf_id` 含相对路径哈希,改算法会让已有产物全部失效 |
| `nlnotes/extract.py` | 分页文本、位图/矢量图抽取、图注推测、可选 OCR | 抽取参数改动需 `extract --force` 才生效 |
| `nlnotes/evidence.py` | 证据索引、token 依据、术语匹配 | 短的全大写缩写(`AS`/`AD`/`TE`)必须大小写敏感匹配,否则会误命中 `address`/`state`/`such as` |
| `nlnotes/taskgen.py` | 任务包生成 | `TASK_MD` 用 `str.format`,模板里的 JSON 花括号必须写成 `{{` `}}` |
| `nlnotes/verify.py` | 9 组门禁 | 覆盖率只统计正文小节页(`body_pages`),**不要**把测验页算进去,否则反超纲检查 `X011` 会失效 |
| `nlnotes/visuals.py` | 动画/图渲染 | 所有外部工具(mmdc/dot/ffmpeg/OCR/图像 API)缺失时必须自动降级,不能抛异常中断 |
| `nlnotes/assemble.py` | Markdown 组装 | 模板用 `StrictUndefined`,新增可选字段要在 `_normalize()` 里补默认值 |
| `schemas/note.schema.json` | AI 输出契约 | `additionalProperties: false`,加字段要同时改 `_template()` 与 `_normalize()` |

任何代码改动后请跑 `python tests/run_e2e.py`。它会造一份合成 PDF 跑完整流水线,
并验证 **14 个臆想反例**都被门禁拦下 —— 这是回归保护的主要手段。

## Cursor Cloud specific instructions

**Cloud VM 上没有用户的 `D:\NetworkLessons\All-Courses-v3.0`。**
所以在 Cloud Agent 里只能开发与测试工具链本身,用 `tests/make_sample_pdf.py`
生成的合成 PDF 验证;**不要假装能读到真实课程 PDF,也不要编造抽取结果**。

环境准备(仓库里没有 `.cursor/environment.json`,需手动装):

```bash
sudo apt-get install -y python3.12-venv     # Debian/Ubuntu 上 venv 需要单独装
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python tests/run_e2e.py           # 验收:期望 ✅ 全部自测通过
```

Linux 上中文字体一般能自动探测到 `/usr/share/fonts/truetype/wqy/wqy-microhei.ttc`;
探测不到就 `sudo apt-get install -y fonts-wqy-microhei`,否则自制图里的中文会变方块。

云端可选工具的现状:`ffmpeg` 有;`mmdc`(mermaid-cli)与 `dot`(graphviz)没有
—— 缺失时会自动降级为内联代码块,这是**预期行为**,不是 bug,不要为此报错或去装它们。

## 更多文档

| 文档 | 内容 |
| --- | --- |
| [`docs/00-总体方案.md`](docs/00-总体方案.md) | 完整方案与执行步骤(先看这个) |
| [`docs/01-环境安装.md`](docs/01-环境安装.md) | 三平台安装、OCR 与 AI 图配置 |
| [`docs/02-流水线详解.md`](docs/02-流水线详解.md) | 每阶段输入输出、全部配置项含义 |
| [`docs/03-AI执行手册.md`](docs/03-AI执行手册.md) | AI 逐步操作、各类工具接法、批量调度 |
| [`docs/04-验收与自测.md`](docs/04-验收与自测.md) | 门禁完整清单、自测、人工抽检 |
| [`docs/05-常见问题.md`](docs/05-常见问题.md) | 抽不到图、中文方块、覆盖度过不了等 |
| [`docs/06-会话交接.md`](docs/06-会话交接.md) | **历史决策、踩过的坑、当前进度、下一步** |
