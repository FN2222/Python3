<#
.SYNOPSIS
    NetworkLessons PDF -> 中文笔记 一键流水线(Windows PowerShell)

.DESCRIPTION
    默认执行"准备阶段"(scan + extract + tasks),并列出接下来该让 AI 写哪几章。
    AI 写完 note.json 后,用 -BuildOnly 执行"校验 + 渲染 + 组装"。

.EXAMPLE
    # 首次:建虚拟环境 + 装依赖 + 准备全部课程
    .\scripts\Run-Pipeline.ps1 -SourceRoot "D:\NetworkLessons\All-Courses-v3.0" -Install

.EXAMPLE
    # 只准备 OSPF 相关的前 3 章(建议先这样试跑)
    .\scripts\Run-Pipeline.ps1 -Filter OSPF -Limit 3

.EXAMPLE
    # AI 写完 note.json 后,出笔记
    .\scripts\Run-Pipeline.ps1 -BuildOnly
#>
[CmdletBinding()]
param(
    [string]$SourceRoot,
    [string]$NotesDir,
    [string]$Filter,
    [int]$Limit = 0,
    [string[]]$Id,
    [switch]$Install,
    [switch]$BuildOnly,
    [switch]$Force,
    [switch]$SkipDoctor
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

# ---------------------------------------------------------------- Python 解释器

$venvPy = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    if ($Install) {
        Write-Host "==> 创建虚拟环境 .venv" -ForegroundColor Cyan
        python -m venv .venv
    }
    if (-not (Test-Path $venvPy)) { $venvPy = "python" }
}

if ($Install) {
    Write-Host "==> 安装依赖" -ForegroundColor Cyan
    & $venvPy -m pip install --upgrade pip
    & $venvPy -m pip install -r requirements.txt
}

# ---------------------------------------------------------------- 配置与参数

if (-not (Test-Path (Join-Path $repo "config\pipeline.json"))) {
    Write-Host "==> 生成 config\pipeline.json" -ForegroundColor Cyan
    & $venvPy -m nlnotes init
}

$common = @()
if ($SourceRoot) { $common += "--source-root"; $common += $SourceRoot }
if ($NotesDir)   { $common += "--notes-dir";   $common += $NotesDir }

$select = @()
if ($Id)          { $select += "--id"; $select += $Id }
if ($Filter)      { $select += "--path"; $select += $Filter }
if ($Limit -gt 0) { $select += "--limit"; $select += "$Limit" }

$selectWithForce = $select
if ($Force) { $selectWithForce = $select + @("--force") }

# 直接调用,不返回值 —— PowerShell 里函数返回值会和命令输出混在一起,
# 所以统一在调用之后读 $LASTEXITCODE。
function Invoke-NlNotes {
    param([string[]]$NlArgs)
    Write-Host "`n> nlnotes $($NlArgs -join ' ')" -ForegroundColor DarkGray
    & $venvPy -m nlnotes @NlArgs
}

# ---------------------------------------------------------------- 体检

if (-not $SkipDoctor) {
    Write-Host "`n==> 环境体检" -ForegroundColor Cyan
    Invoke-NlNotes (@("doctor") + $common)
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "体检发现问题(见上)。可用 -SkipDoctor 跳过,但自制图的中文可能显示为方块。"
    }
}

# ---------------------------------------------------------------- 主流程

if ($BuildOnly) {
    Write-Host "`n==> 校验 + 渲染 + 组装" -ForegroundColor Cyan
    Invoke-NlNotes (@("build") + $common + $selectWithForce)
    $rc = $LASTEXITCODE
    Invoke-NlNotes (@("status", "--detail") + $common)
    if ($rc -ne 0) {
        Write-Warning "部分章节未通过门禁。报告在 build\reports\<pdf_id>.json;修订规则见 prompts\40-修订循环.md"
    } else {
        Write-Host "`n✅ 全部通过,笔记已生成在 notes\" -ForegroundColor Green
    }
    exit $rc
}

Write-Host "`n==> 准备阶段:scan + extract + tasks" -ForegroundColor Cyan
Invoke-NlNotes (@("prepare") + $common + $selectWithForce)
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "`n===== 接下来让 AI 处理这些章节 =====" -ForegroundColor Yellow
Invoke-NlNotes (@("next", "--count", "5") + $common + $select)

Write-Host @"

下一步(把下面这段话交给 AI):

  读 build/tasks/<id>/TASK.md 并严格按它的要求产出 build/tasks/<id>/OUTPUT/note.json。
  figures.md 里的每张图都要打开看,把图上的文字登记到 labels_seen。
  写完运行  python -m nlnotes build --id <id>  ,按 build/reports/<id>.json 的报告
  逐条修到通过为止。不要修改门禁配置。

同时把 prompts/00-system-中文笔记作者.md 设为 AI 的系统提示词。
AI 写完后运行:  .\scripts\Run-Pipeline.ps1 -BuildOnly
"@ -ForegroundColor Yellow
