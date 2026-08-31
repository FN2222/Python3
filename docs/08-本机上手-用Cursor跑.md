# 本机上手:用 Cursor(Grok 4.6)跑这套工具链

> 目标:在你自己的 Windows 机器上跑通,并且**让 Cursor 里的 Grok 4.6 充当撰写者**,
> 不需要任何 API Key。全文的命令和提示词都可以直接复制。

---

## ⚠️ 开始之前:确认你在哪台机器上

本文所有命令都必须在**你本机的 Windows PowerShell** 里跑。
如果你正在用 Cursor 的 **Cloud Agent**(云端 agent),它的终端是**远程 Linux 机器**,
那台机器上**没有你的 D 盘**,在那里跑这些命令一定失败。

怎么分辨:

| 提示符长这样 | 是哪台机器 | 能不能跑本文的命令 |
| --- | --- | --- |
| `PS D:\>` 或 `PS C:\Users\你>` | ✅ 你本机的 Windows PowerShell | 可以 |
| `workspace $`,或标签写着 `bash` | ❌ 云端 agent 的 Linux 终端 | **不行** |

不确定就先敲一下 `pwd`:本机显示 `D:\...` 之类,云端显示 `/workspace`。

**最稳的起步方式**:先不用 Cursor 的终端 —— 按 `Win` 键搜 **PowerShell** 打开,
在里面完成下面第 1 节的克隆,然后再用 Cursor 的 `File` → `Open Folder`
打开克隆出来的目录。这时 Cursor 窗口连的才是本机。

> 另外注意:**不要把带行尾反斜杠的命令粘到 bash 里**。
> bash 把行尾 `\` 当续行符,`cd D:\` 会把下一行吞掉,
> 结果是 `cd: too many arguments`,而且后面的 `git clone` 根本没执行。
> 本文已统一改成不带尾部反斜杠的写法。

---

## 0. 先搞清楚谁花什么

| 环节 | 谁在干 | 花什么 |
| --- | --- | --- |
| 扫描 / 体检 / 抽取 / 生成任务包 / 门禁校验 / 渲染动画 / 出 Markdown | 本机 Python | **免费** |
| 撰写 `note.json`、`interview.json` | **Grok 4.6(在 Cursor 里)** | **Cursor 的请求额度** |

也就是说:**用 Cursor 跑不需要充值任何 API**,消耗的是你已有的 Cursor 订阅额度。
每写一章大约消耗几次请求(1 次撰写 + 0~3 次按门禁报告修订)。

**拿不到、也不需要 Grok 4.6 的 Key。** Cursor 不会把这个模型的密钥发给你,
填进 `$env:NLNOTES_API_KEY` 也没用。`nlnotes write` 调的是你自己买的 HTTP API,
跟 Cursor 聊天窗口里的 Grok 是两条路。想全自动无人值守,请另买 DeepSeek / Gemini
等 Key,步骤见 [`05-常见问题.md`](05-常见问题.md) 的「购买与使用 API Key」。

> 另一条路是 `nlnotes write` 直接调 API(见 [`07-批量自动化与成本.md`](07-批量自动化与成本.md))。
> 两者**质量下限完全一样**,因为把关的是本地门禁,不是模型。
> 差别只在:Cursor 方便、按请求数计;API 便宜、可以完全无人值守跑一整晚。
> 建议:**先用 Cursor 跑几章确认效果**,量大了再考虑切 API。

---

## 1. 一次性准备(约 10 分钟)

### 1.1 把仓库弄到本机

打开**本机的 PowerShell**(按 `Win` 搜 PowerShell),二选一:

**如果你本机还没有这个仓库:**

```powershell
cd D:
git clone https://github.com/FN2222/Python3.git
cd Python3
git checkout cursor/networklessons-pdf-to-chinese-notes-pipeline-ec2b
```

> 写成 `cd D:` 而不是 `cd D:\` 是故意的 —— 前者在 PowerShell 里同样能切到 D 盘,
> 而且万一粘错到 bash 里也不会吞掉下一行命令。

#### 克隆失败怎么办(公司电脑常见)

如果报下面这个错:

```
fatal: unable to access 'https://github.com/...': schannel: SEC_E_UNTRUSTED_ROOT
(0x80090325) - 证书链是由不受信任的颁发机构颁发的
```

这是**公司网络做 HTTPS 审查**导致的:中间设备把证书换成了公司自签证书,
Git 的 schannel 后端做吊销检查时取不到 CRL,于是报成"根不受信任"。

**第一步,先试这一行**(只关掉吊销检查,证书本身照常校验,90% 的情况能解决):

```powershell
git config --global http.schannelCheckRevoke false
git clone https://github.com/FN2222/Python3.git
```

顺手修一下 PowerShell 的控制台乱码,以后报错能看清中文:

```powershell
chcp 65001
```

**第二步,还不行就直接下 ZIP —— 跑这套工具链根本不需要 git。**
仓库是公开的,浏览器能直接下载:

```
https://github.com/FN2222/Python3/archive/refs/heads/cursor/networklessons-pdf-to-chinese-notes-pipeline-ec2b.zip
```

解压后的文件夹名会是 `Python3-cursor-networklessons-pdf-to-chinese-notes-pipeline-ec2b`,
**把它重命名为 `Python3`**(得到 `D:\Python3`),后面步骤完全一样。
代价是以后没法 `git pull` 更新,需要重新下 ZIP。

**第三步(可选),彻底修好 git**:从 `certmgr.msc` →「受信任的根证书颁发机构」
导出公司那张 CA 证书,追加到 Git 的 `ca-bundle.crt`
(位置一般是 `C:\Program Files\Git\mingw64\etc\ssl\certs\ca-bundle.crt`),
或者把它导入到 Git 使用的证书存储里。

> **不要**用 `git config --global http.sslVerify false` 全局关掉证书校验 ——
> 那等于放弃 HTTPS 的身份验证,在公司网络里风险更大。

**如果本机已经有了:**

```powershell
cd <你的仓库目录>
git fetch origin cursor/networklessons-pdf-to-chinese-notes-pipeline-ec2b
git checkout cursor/networklessons-pdf-to-chinese-notes-pipeline-ec2b
```

然后用 Cursor 打开这个目录(`File` → `Open Folder`)。
仓库里有 `AGENTS.md` 和 `.cursor/rules/`,**Cursor 会自动读取**,
所以 Grok 一上来就知道这个项目的规则,不需要你解释。

> 仓库放哪都行,不必和 `D:\NetworkLessons` 在一起 —— 课程目录是通过配置指定的。

### 1.1.5 以后怎么更新代码

**最省事的办法(推荐,不依赖 git):**

```powershell
cd D:\Python3
.\scripts\Update.ps1 -UpgradeConfig
```

#### 首次自助更新(本地脚本报缺少 `}` ,或 Invoke-WebRequest 报 TLS)

不要再跑本机那份旧的 `Update.ps1`,也不要用 `Invoke-WebRequest` ——
你的环境里前者编码坏了,后者会被公司网络拦掉。
`init --upgrade` 显示「配置已是最新」**不等于代码已更新**,只说明旧配置字段还在。

**先试这一段**(用 Windows 自带的 `curl.exe`,绕过 .NET 的证书链问题):

```powershell
cd D:\Python3
$ErrorActionPreference = "Stop"
$b = "cursor/networklessons-pdf-to-chinese-notes-pipeline-ec2b"
$url = "https://github.com/FN2222/Python3/archive/refs/heads/$b.zip"
$t = Join-Path $env:TEMP "nl-up"
$zip = Join-Path $t "s.zip"
Remove-Item $t -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory $t | Out-Null
Write-Host "downloading with curl.exe ..."
curl.exe --ssl-no-revoke -L --fail -o $zip $url
if (-not (Test-Path $zip)) { throw "download failed" }
if ((Get-Item $zip).Length -lt 10000) { throw "download too small, not a zip" }
Expand-Archive $zip $t -Force
$src = (Get-ChildItem $t -Directory | Select-Object -First 1).FullName
robocopy $src . /E /NFL /NDL /NJH /NJS /NP /XF pipeline.json selection.txt `
  /XD build notes out .venv | Out-Null
Remove-Item $t -Recurse -Force
.\.venv\Scripts\python.exe -m nlnotes init --upgrade
.\.venv\Scripts\python.exe -m nlnotes doctor
```

成功的话,`doctor` 第一行应显示 `nlnotes 1.1.2`(或更新)。然后就可以:

```powershell
.\scripts\Update.ps1 -UpgradeConfig
```

新脚本是纯 ASCII,PowerShell 5.1 不会再因为编码报缺少 `}`。

**curl 也失败时:浏览器下载,不要手工解压**

1. 浏览器打开:
   https://github.com/FN2222/Python3/archive/refs/heads/cursor/networklessons-pdf-to-chinese-notes-pipeline-ec2b.zip
2. 看下载文件夹里实际文件名,在 PowerShell 里跑(只改第一行路径):

```powershell
cd D:\Python3
$zip = "$env:USERPROFILE\Downloads\Python3-cursor-networklessons-pdf-to-chinese-notes-pipeline-ec2b.zip"
dir $zip
$t = Join-Path $env:TEMP "nl-up"
Remove-Item $t -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory $t | Out-Null
Expand-Archive $zip $t -Force
$src = (Get-ChildItem $t -Directory | Select-Object -First 1).FullName
robocopy $src . /E /NFL /NDL /NJH /NJS /NP /XF pipeline.json selection.txt `
  /XD build notes out .venv | Out-Null
Remove-Item $t -Recurse -Force
.\.venv\Scripts\python.exe -m nlnotes init --upgrade
.\.venv\Scripts\python.exe -m nlnotes doctor
```

`dir $zip` 必须能列出文件;若报找不到,把 `$zip` 改成 `dir $env:USERPROFILE\Downloads\*.zip` 看到的那个真实名字。
`config`、`build`、`notes`、已通过的 5 章笔记都不会被动到。

下面是分情况的手工做法。先判断你当初是怎么拿到代码的:

```powershell
cd D:\Python3
git status
```

**能正常输出分支信息** → 有 git,一条命令搞定:

```powershell
git pull
```

**报 `not a git repository`,或者 `git pull` 一直报证书错误** → 用一键更新脚本
(不依赖 git,走 Windows 证书存储,浏览器能上 GitHub 它就能下):

```powershell
cd D:\Python3
.\scripts\Update.ps1 -UpgradeConfig
```

它会自动下载分支 ZIP、覆盖代码、并补齐配置项。加 `-ReExtract` 可以顺手重跑抽取。
脚本会明确跳过你的东西:`config\pipeline.json`、`config\selection.txt`、
`build\`、`notes\`、`.venv\`。

脚本也下载失败的话,再退回浏览器手动下载并**覆盖解压**到 `D:\Python3`。

覆盖时会发生什么(不用你手动挑文件):

| 会被覆盖 | 不会被动到 |
| --- | --- |
| `nlnotes\`(代码)、`docs\`、`prompts\`、`schemas\`、`templates\`、`glossary\`、`scripts\`、`tests\`、`examples\` | `config\pipeline.json`(**你的配置**) |
| `README.md`、`AGENTS.md`、`requirements.txt`、`.cursor\` | `build\`(已抽取的原文与图片) |
| `config\pipeline.example.json`(只是示例模板) | `notes\`(已生成的笔记)、`.venv\`(虚拟环境) |

右侧那几项**不在仓库里**(被 `.gitignore` 排除),所以 ZIP 包里根本没有它们
—— 你的配置和虚拟环境都不会丢,也不用重装依赖。

> 唯一要留意:ZIP 解压出来的顶层文件夹名很长
> (`Python3-cursor-networklessons-...`),要把**它里面的内容**覆盖进 `D:\Python3`,
> 而不是把整个文件夹丢进去变成 `D:\Python3\Python3-cursor-...`。

**更新完必须做两件事:**

1. **补齐配置文件的新增项。** `config/pipeline.json` 是你第一次 `init` 时的快照,
   新版本增加的配置项不会自动出现在里面(功能会用默认值兜底,但你看不到也改不了):

   ```powershell
   .\.venv\Scripts\python.exe -m nlnotes init --upgrade
   ```

   它保留你改过的所有值,只补缺少的项,并备份原文件。
   `init` 与 `doctor` 都会主动提示配置是否为旧版。

2. **如果改动涉及抽取阶段**(噪声清理、图片参数、OCR),必须加 `--force` 重跑,
   否则会直接复用旧的抽取结果:

   ```powershell
   .\.venv\Scripts\python.exe -m nlnotes extract --force
   .\.venv\Scripts\python.exe -m nlnotes tasks --force
   ```

   `tasks --force` 只重写任务包的输入文件,**不会动已写好的 `OUTPUT/note.json`**。

### 1.2 Python 与依赖

需要 Python 3.10 以上。没装的话去 python.org 装,**记得勾选 Add to PATH**。

```powershell
python --version                      # 确认 3.10+
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

> **为什么用 `.\.venv\Scripts\python.exe` 而不是先 `Activate.ps1`?**
> Windows 默认的 PowerShell 执行策略常常会拦掉 `Activate.ps1`,
> 直接调 `python.exe` 可以绕过这个问题,少一个坑。
> 下文所有命令都用这种写法,你也可以让 Grok 一律这么写。

### 1.3 生成并修改配置

```powershell
.\.venv\Scripts\python.exe -m nlnotes init
```

然后打开 `config\pipeline.json`,至少改这几项:

```json
{
  "source_root": "D:/NetworkLessons/All-Courses-v3.0",
  "font_path": "C:/Windows/Fonts/msyh.ttc",
  "figure_ocr": true
}
```

三点说明:

- **`source_root` 必须用正斜杠 `/` 或双反斜杠 `\\`** —— JSON 里单反斜杠是转义符,会报错。
- `font_path` 是自制动画里中文的字体。没有微软雅黑就用 `C:/Windows/Fonts/simhei.ttf`。
- **`figure_ocr` 是可选项,装不上就跳过,不要在这里耗时间。**
  它的作用是把拓扑图里的 `R1`、`Gi0/1`、`10.0.0.0/24` 提取到任务包里
  —— 这些文字只存在于图片像素中,不在 PDF 文本层。
  开了 OCR,Grok 不必"看图"也能正确引用;不开,就让 Grok 直接打开图片文件看
  (Grok 4.6 支持读图),**提示词里已经明确要求它看图**,而且门禁会兜底:
  没看图瞎填标签会被 `T001` 拦下。

  想装的话:

  ```powershell
  .\.venv\Scripts\python.exe -m pip install pytesseract
  winget install UB-Mannheim.TesseractOCR
  ```

  **公司电脑上 winget 常会失败**(`尝试更新源失败: winget` —— 源更新被网络拦了,
  和上面 git 的证书问题同一个根因)。两个办法:

  ```powershell
  winget source reset --force
  winget install UB-Mannheim.TesseractOCR
  ```

  或者浏览器打开 <https://github.com/UB-Mannheim/tesseract/wiki> 下 exe 安装包
  (浏览器访问 GitHub 是通的)。

  **都不行就把 `figure_ocr` 保持 `false` 直接往下走**,后面想装了再回来开,
  开启后需要重跑 `nlnotes extract --force`。

### 1.4 体检

```powershell
.\.venv\Scripts\python.exe -m nlnotes doctor
```

期望看到课程根目录 ✅ 存在、依赖全部 ✅、中文字体有路径。
`mmdc` / `dot` 显示 ➖ 是正常的(缺失会自动降级成内联代码块,不影响出笔记)。

---

## 2. 第一步:让 Grok 跑体检与准备,并生成诊断报告

**在 Cursor 的 Agent 面板选 Grok 4.6,把下面这段整段粘进去:**

```
请在本机跑通 nlnotes 的准备阶段,然后生成诊断报告。

环境约定:
- 一律用 .\.venv\Scripts\python.exe 调用 Python,不要用 Activate.ps1(会被执行策略拦)
- 课程目录在 config/pipeline.json 的 source_root,不要改动课程目录里的任何文件

请按顺序执行,每步跑完把关键输出贴给我:

1. .\.venv\Scripts\python.exe -m nlnotes doctor
2. .\.venv\Scripts\python.exe -m nlnotes scan
3. .\.venv\Scripts\python.exe -m nlnotes audit
4. .\.venv\Scripts\python.exe -m nlnotes prepare --path OSPF --limit 3
5. .\.venv\Scripts\python.exe -m nlnotes diag

如果某一步报错,先读报错信息自己判断能不能修(比如缺依赖就装),
修不了就停下来告诉我具体的报错。

最后请做两件事:
- 把 build/diagnosis.md 的完整内容贴出来
- 用你自己的话总结:课程一共多少个 PDF、体检剔除了几个、
  抽取出的图片数量看起来是否合理、原文文本层有没有乱码
```

跑完之后你会得到 `build\diagnosis.md`。**把这个文件的内容发我**,
我据此判断抽取参数要不要调(比如图抽多了/抽少了、矢量图没识别出来)。

这份报告只有统计和少量样本,不含课程正文大段内容,可以放心分享。

### 这一步大概会看到什么

- `audit` 可能会剔除一些 PDF。**被剔除不代表文件坏了**,最常见的原因是扫描件
  (整页是图片、没有文本层)。报告里会写清原因和处理办法。
- `prepare --path OSPF --limit 3` 只处理 OSPF 相关的前 3 个,故意小范围,
  就是为了先看效果、别一上来跑几百个。

---

## 3. 第二步:让 Grok 写第一章笔记

**先看该写哪一章:**

```powershell
.\.venv\Scripts\python.exe -m nlnotes next --count 3
```

它会打出 `pdf_id` 和任务包路径。然后**把下面这段粘给 Grok**
(把 `<PDF_ID>` 换成上一步打出来的那个 id):

```
请按任务包的要求,为这一章产出中文笔记。

pdf_id: <PDF_ID>

必读(按顺序):
1. prompts/00-system-中文笔记作者.md   ← 这是你必须遵守的铁律
2. build/tasks/<PDF_ID>/TASK.md         ← 本章的具体要求与阈值,以它为准
3. build/tasks/<PDF_ID>/source-text.md  ← 原文全文,页码标记为 [[p.N]]
4. build/tasks/<PDF_ID>/outline.md
5. build/tasks/<PDF_ID>/figures.md      ← 可用图清单
6. build/tasks/<PDF_ID>/glossary.md     ← 术语统一译名
7. build/tasks/<PDF_ID>/codeblocks.md
8. build/tasks/<PDF_ID>/note.schema.json 与 note.template.json

几条必须做到的:
- 每条知识点的 text_en_quote 必须从 source-text.md 里**复制粘贴**,不要凭理解写
- figures.md 里的每张图都要打开图片文件实际看一遍,把图上读到的文字
  逐字登记到 figures[].labels_seen(拓扑图里的文字不在 PDF 文本层,
  不登记就会被门禁判为臆想)
- 笔记要详尽:多用 points[].detail_zh 把机制、前提、例外讲透,
  不要写一层标题式的空洞概括(有知识点密度门禁会拦)
- 费曼部分要写全:大白话复述、必须掌握清单、难点分析、自测题
- 不要写任何原文没有的协议、命令、数值、IP

产出:build/tasks/<PDF_ID>/OUTPUT/note.json

写完后运行:
  .\.venv\Scripts\python.exe -m nlnotes build --id <PDF_ID>

如果不通过,读 build/reports/<PDF_ID>.json 的 errors,
按 prompts/40-修订循环.md 的错误码对照表逐条修 note.json,然后重跑。
最多修 5 轮;5 轮还过不了就停下来把剩余错误告诉我。

**不要修改门禁配置、不要下调阈值、不要删内容来规避错误。**
```

通过之后,笔记在 `notes\<方向>\<协议>\<课程名>.md`。
用 Typora 或 Obsidian 打开看效果(GIF 动画会自动播放)。

---

## 4. 第三步:确认风格后批量推进

### 4.1 一次让 Grok 做一批

**完整的批量提示词在 [`prompts/60-批量流水作业.md`](../prompts/60-批量流水作业.md)** ——
它让 AI 一条消息连续做完 5 章:自己取任务、读输入、看图、写 note.json、
跑校验、按报告修订,做完汇报每章用了几轮。做完一批把同一段再发一次就接着下一批。

下面是简化版模板:

```
请依次为下面这几章产出笔记,一章一章来,每章都要跑到门禁通过再进入下一章:

<PDF_ID_1>
<PDF_ID_2>
<PDF_ID_3>

规则同上:遵守 prompts/00-system-中文笔记作者.md,
读各自的 build/tasks/<id>/TASK.md,图要打开看并登记 labels_seen,
写完跑 .\.venv\Scripts\python.exe -m nlnotes build --id <id>,
按报告修到通过。

全部做完后,汇总告诉我:每章用了几轮、有没有反复出现的同类错误。
```

**最后那句很重要** —— 如果同一类错误反复出现,说明提示词或参数要调,
而不是每章都硬修。把它反馈给我,我来调。

获取下一批 id:

```powershell
.\.venv\Scripts\python.exe -m nlnotes next --count 5
```

随时看整体进度:

```powershell
.\.venv\Scripts\python.exe -m nlnotes status --detail
```

### 4.2 某个协议的章节都写完后,做面试复习笔记

```powershell
.\.venv\Scripts\python.exe -m nlnotes groups --list      # 看各协议完成了几章
.\.venv\Scripts\python.exe -m nlnotes groups --group OSPF
```

然后粘给 Grok:

```
请产出 OSPF 的协议级面试复习笔记。

必读:
1. prompts/50-面试复习.md                    ← 系统提示词,**不要**用章节笔记那份
2. build/groups/igp-ospf/TASK.md              ← 具体要求,以它为准
3. build/groups/igp-ospf/chapters.md          ← 出题素材(含 pdf_id 与页码)
4. build/groups/igp-ospf/interview.schema.json
5. 需要复制英文原句时,回 build/extract/<pdf_id>/text.md 取

你的身份:15 年经验的资深网络与安全架构专家 + 大厂技术面试官。
要产出:知识体系图、跨章必须掌握清单、高频必考原理题(高分答题模板 + 得分要点)、
场景化面试题(情景模拟 + 解题框架)、面试官连环追问(正好三层递进)、避坑指南。
问题与答案全部中英双语。

**发散的边界(最重要)**:
- 题目的核心答案、原理、机制、数值、判定顺序 → 必须能在 grounding 指向的原文页找到
- 工程经验、厂商差异、版本演进、跨协议对比 → 只能放 extension_zh / extension_en,
  会被渲染成"课程外扩展"独立区块

产出:build/groups/igp-ospf/OUTPUT/interview.json

写完运行:
  .\.venv\Scripts\python.exe -m nlnotes build-group --group OSPF

按 build/reports/group-igp-ospf.json 的报告逐条修到通过。
```

产出在 `notes\<方向>\<协议>\00-面试复习-<协议>.md`。

### 4.3 收尾

```powershell
.\.venv\Scripts\python.exe -m nlnotes index          # 重建 notes\README.md 导航
.\.venv\Scripts\python.exe -m nlnotes status --detail
```

---

## 5. 用 Cursor 跑的几个注意点

### 5.1 让 Grok 一次只做一章

同时开多章最容易出的错是**页码串了** —— 把 A 章的内容标成 B 章的页码。
提示词里明确"一章一章来,通过了再进入下一章"。

### 5.2 别让它"帮你优化"门禁

模型有时会自作聪明:改 `config/pipeline.json` 的阈值、往 `token_whitelist` 里
塞协议名、或者删掉内容让覆盖度检查通过。这些都会让笔记失去可信度。
`AGENTS.md` 和 `.cursor/rules/nlnotes.mdc` 里已经写明禁止,
但如果你发现它这么干了,直接让它 `git checkout config/pipeline.json` 还原。

### 5.3 图要真的看

如果你没开 OCR,一定要在提示词里强调"打开 `figures.md` 里的每张图片实际看一遍"。
Grok 4.6 能读图,但如果不明确要求,它可能只读 `figures.md` 的文字描述就开始写,
结果 `labels_seen` 填错,被门禁 `T001` 拦下。

开了 OCR 的话,图上的文字会直接出现在 `figures.md` 里,这个风险就基本消除了
—— 这也是我建议开 OCR 的主要原因。

### 5.4 请求额度的取舍

粗算:每章 1 次撰写 + 平均 1~2 次修订 ≈ 2~3 次请求。
几十章还好,几百章就比较可观了。所以:

- **前期用 Cursor**:方便,能随时看到它在干什么,便于调风格;
- **确认风格稳定后考虑切 API**:`nlnotes write` 可以挂着跑一整晚,
  单章成本几分钱到几毛钱人民币的量级,而且不占 Cursor 额度。
  切换只需在 `config/pipeline.json` 填 `writer_base_url` / `writer_model`
  并设一个环境变量,笔记质量不受影响(门禁一样严)。

### 5.5 中断了怎么办

随时可以停。已经通过门禁的章节不会被重做:

- `nlnotes next` 只列还没写的;
- `nlnotes write`(如果你后来切了 API)会自动跳过已通过的;
- `nlnotes status --detail` 显示每章处于哪个阶段。

---

## 6. 出问题时最快的自查路径

| 现象 | 先看这里 |
| --- | --- |
| `bash: cd: too many arguments` / `cd: Python3: No such file or directory` | **跑错终端了** —— 你在云端 agent 的 bash 里,不是本机 PowerShell。见本文开头的警告 |
| `schannel: SEC_E_UNTRUSTED_ROOT` 克隆失败 | 公司网络 HTTPS 审查;先试 `git config --global http.schannelCheckRevoke false`,不行就下 ZIP。见第 1.1 节 |
| PowerShell 里中文报错是乱码 | 先执行 `chcp 65001` |
| `尝试更新源失败: winget` | winget 源被公司网络拦了。OCR 是可选项,直接把 `figure_ocr` 保持 `false` 往下走 |
| `pip install` 报 SSL 证书错误 | 加参数:`--trusted-host pypi.org --trusted-host files.pythonhosted.org` |
| 命令报 `课程根目录不存在` | `config\pipeline.json` 的 `source_root` 是不是写了单反斜杠 |
| 扫描到 0 个 PDF | 路径对不对;文件是不是真的 `.pdf` |
| 大量 PDF 被 audit 剔除 | `build\audit.md` 的原因列;多半是扫描件,需要先 OCR |
| 一张图都没抽到 | `build\diagnosis.md` 的第四节;可能要调 `figure_min_*` 或 `vector_min_drawings` |
| 自制图里中文是方块 | `config` 的 `font_path` 没设或路径错 |
| 门禁反复报同一类错误 | `prompts\40-修订循环.md` 的错误码对照表;若是系统性问题请反馈给我 |
| 不知道现在做到哪了 | `nlnotes status --detail` 与 `notes\README.md` |

更多见 [`05-常见问题.md`](05-常见问题.md)。

---

## 7. 现在就做这两件事

1. 按第 1 节把环境装好;
2. 把第 2 节那段提示词粘给 Grok 4.6,跑完把 `build\diagnosis.md` 的内容发我。

我看到诊断报告后,会给出针对你真实 PDF 排版的参数调整建议 —— 这是目前唯一还需要我介入的环节。
之后的批量生产你自己跑就行。
