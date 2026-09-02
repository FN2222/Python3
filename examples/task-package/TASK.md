# 制作任务 — OSPF Neighbor Adjacency

> 本文件是**唯一入口**。请严格按此执行,不要引入任何本任务包之外的知识。

## 0. 任务目标

把英文 PDF 课程《OSPF Neighbor Adjacency》做成一份**中文学习笔记**,要求:

1. 知识点配上**原文中的拓扑图**(引用 `figures.md` 中的 figure_id)。
2. 抽象/难懂的地方,用**自制动画或分步静态图**讲清楚(`visuals`,由本工具渲染,不需要你画)。
3. 章末用**费曼学习法**出题检验,题目与答案都要**中英文双版**。
4. **严格限定在本章原文范围内**:不发散、不臆想、不补充课外知识。

## 1. 输入(全部只读,禁止修改)

| 文件 | 用途 |
| --- | --- |
| `source-text.md` | 原文全文,每页以 `[[p.N]]` 开头,页码引用必须与之一致 |
| `figures.md` | 可用图片清单 + 每张图的原文上下文 |
| `glossary.md` | 本章术语的统一中文译名 |
| `codeblocks.md` | 原文中的配置/命令块(可逐字引用) |
| `context.json` | 机器可读上下文(页数、图列表、阈值等) |
| `note.schema.json` | 你的输出必须符合的结构 |
| `note.template.json` | 骨架模板,照着填最省事 |

源 PDF: `IGP/OSPF/OSPF Neighbor Adjacency.pdf` — **只读,永远不要改动或移动它。**

## 2. 输出

只需产出**一个文件**:

```
build/tasks/ospf-neighbor-adjacency-69619352/OUTPUT/note.json
```

它必须是符合 `note.schema.json` 的 JSON。Markdown 排版、图片拷贝、动画渲染、
测验排版全部由 `nlnotes build` 自动完成,**你不要手写 Markdown**。

## 3. 硬约束(违反即门禁失败)

### 3.1 每条知识点必须有原文出处

`sections[].points[]` 每一项都要:

- `text_en_quote`: 从 `source-text.md` **逐字复制**的英文原句(可用 ` ... ` 省略中间部分),
  长度 ≥ 12 字符。门禁会把它和你声明的那一页做模糊比对,阈值 **90**。
- `page`: 该句所在页码(1 ~ 4)。
- `text_zh`: 这句话的中文讲解。**只能翻译/解释 `text_en_quote` 里已有的信息**,
  不得添加原文没有的例子、数字、协议、结论、生产经验。

### 3.2 禁止出现原文没有的技术词与数字

门禁会扫描你所有中文字段里的英文单词、IP 地址、数字(≥2 位),
逐个检查是否出现在原文中。**编造一个协议名、一个定时器数值、一个 IP,都会直接失败。**

### 3.3 禁止发散措辞

以下词一律不得出现:据说、笔者认为、我认为、个人觉得、可能是因为、推测、一般业界、众所周知、扩展阅读、题外话 等

### 3.4 图片只能引用真实存在的,且必须登记图上标签

`figures[].figure_id` 必须来自 `figures.md`。本章共有 **2** 张可用图,
门禁要求至少引用其中 **1** 张(可用图为 0 时不做此要求)。

拓扑图里的设备名(R1/SW1)、接口名、网段(10.0.0.0/24)这些文字**只存在于图片像素里,
不在 PDF 文本层**。因此:**打开 `figures.md` 里给出的图片预览路径看图**,
把你读到的标签逐字填进 `figures[].labels_seen`。登记过的标签才允许出现在中文讲解中。
未登记就使用 `R2`、`192.168.12.0/24` 之类的字样,会被判为臆想。

### 3.5 内容覆盖度

被引用的页码必须覆盖正文页的 **80%** 以上
(本章正文页共 4 页,页号见 `context.json` 的 `content_pages`)。
不允许只挑简单段落做,漏掉大段内容。

### 3.6 配置/命令逐字引用

`configs[].code` 必须逐字复制原文,不得改写、补全、纠错、翻译。
中文解释写在 `explain_zh` / `annotations_zh` 里。

## 4. 自制可视化(`sections[].visuals[]`)怎么写

**判断标准:只有当原文的某个点"抽象、多步骤、时序性强、容易混淆"时才自制图。**
每个 visual 都必须填 `why_zh`(说明原文哪个点难懂)和 `grounding`
(≥1 条支撑本图元素的英文原文引用,门禁阈值 88)。

五种 `kind`:

### `packet_flow` — 首选,用于"报文/状态一步步变化"
本工具会渲染成**动画 GIF + 分步静态图 PNG(+MP4)**。规格:

```json
{
  "kind": "packet_flow",
  "spec": {
    "nodes": [
      {"id": "R1", "label": "R1", "role": "router", "x": 0.0, "y": 0.35},
      {"id": "R2", "label": "R2", "role": "router", "x": 1.0, "y": 0.35}
    ],
    "links": [{"from": "R1", "to": "R2", "label": "10.1.1.0/24"}],
    "steps": [
      {"title_zh": "R1 发出 Hello",
        "note_zh": "原文说明这一步做什么(仍须来自原文)",
        "packets": [{"from": "R1", "to": "R2", "label": "Hello"}],
        "highlight_nodes": ["R1"],
        "highlight_links": [["R1", "R2"]],
        "state": {"R1": "Init"}}
    ]
  }
}
```

- `role` 可选: router / switch / host / server / cloud / firewall
- `x`、`y` 为 0~1 相对坐标(不填则自动布局)
- `steps` 建议 3~8 步;`label`、`state` 里的英文必须来自原文
- 节点名(R1/SW1/H1)必须是原文或原文拓扑图里出现过的名字

### `mermaid` — 用于结构、流程判定、层级关系
`spec.code` 写 mermaid 源码(`flowchart` / `sequenceDiagram` / `stateDiagram-v2`)。
装了 mermaid-cli 就渲染成 PNG,否则内联代码块(Obsidian/Typora/GitHub 均可显示)。

### `graphviz` — 用于状态机、树形结构
`spec.dot` 写 DOT 源码。

### `comparison_table` — 用于"A 与 B 的区别"
`spec.headers` + `spec.rows`,内容必须逐项能在原文找到依据。

### `ai_illustration` — 仅用于确实需要类比/隐喻的极抽象概念
`spec.prompt_en`(英文提示词)+ `spec.must_include_labels`(图中允许出现的唯一文字)。
渲染后会自动打上"AI 辅助示意图 · 非 PDF 原图"水印。**每章最多 1 个,能用前四种就不要用这个。**

## 5. 费曼测验(`feynman`)

1. `explain_back_zh`:用最朴素的中文把本章讲给外行听(≥80 字,少用术语),内容仍须来自原文。
2. `questions`:**8 ~ 20 题**,每题必须含
   `q_zh` / `q_en` / `answer_zh` / `answer_en` / `source_pages` / `evidence_quote`。
   - 中英文必须是**同一道题**的两个语言版本,不能是两道不同的题。
   - `answer_en` 应尽量贴合原文表述;`answer_zh` 是它的中文版。
   - `type` 至少覆盖 concept、process;建议按 `difficulty` 1→3 递进。
   - **题目不得超纲**:凡是本章原文没讲的,不能出题。
3. `blind_spots_zh`:本章最容易卡住的点(仍须来自原文内容)。

## 6. 完成后必须自检

```bash
python -m nlnotes build --id ospf-neighbor-adjacency-69619352
```

该命令会依次执行:结构校验 → 原文引用比对 → token 依据检查 → 覆盖度检查 →
渲染可视化 → 生成 Markdown。**若报错,请按报错逐条修正 `note.json` 后重跑,
直到 `verify` 全绿。** 报告在 `build/reports/ospf-neighbor-adjacency-69619352.json`。

常见失败与处理:

| 报错 | 原因 | 处理 |
| --- | --- | --- |
| `引用与原文不匹配` | `text_en_quote` 不是逐字复制,或页码写错 | 回到 `source-text.md` 重新复制 |
| `无原文依据的 token` | 中文里出现了原文没有的词/数字 | 删掉该词,或改用原文里的说法 |
| `figure_id 不存在` | 图 id 写错 | 对照 `figures.md` |
| `覆盖度不足` | 漏掉大段内容 | 补充对应页的 sections/points |
| `引用页码超范围` | 页码 > 4 | 修正页码 |
