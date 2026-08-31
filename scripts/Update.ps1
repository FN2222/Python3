<#
.SYNOPSIS
    一键更新 nlnotes 代码(不依赖 git,适合公司网络下 git 报证书错误的情况)

.DESCRIPTION
    从 GitHub 下载分支 ZIP 并覆盖本地代码文件,自动跳过你的配置与产物:
      不会被动到:config\pipeline.json、config\selection.txt、build\、notes\、.venv\
    下载用的是 PowerShell 的 Invoke-WebRequest,走 Windows 证书存储 ——
    浏览器能访问 GitHub,它一般就能下载成功(而 git 的 schannel 可能因为
    吊销检查失败而报 SEC_E_UNTRUSTED_ROOT)。

.EXAMPLE
    .\scripts\Update.ps1

.EXAMPLE
    # 更新后顺手补齐配置项并重跑抽取
    .\scripts\Update.ps1 -UpgradeConfig -ReExtract
#>
[CmdletBinding()]
param(
    [string]$Branch = "cursor/networklessons-pdf-to-chinese-notes-pipeline-ec2b",
    [string]$Repo = "FN2222/Python3",
    [switch]$UpgradeConfig,
    [switch]$ReExtract,
    [switch]$KeepDownload
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

# 这些是你的东西,永远不覆盖(它们本来也不在 ZIP 里,这里再兜一层保险)
$protected = @(
    "config\pipeline.json",
    "config\selection.txt",
    "build",
    "notes",
    ".venv",
    "out"
)

$zipUrl = "https://github.com/$Repo/archive/refs/heads/$Branch.zip"
$tmp = Join-Path $env:TEMP ("nlnotes-update-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
$zipPath = Join-Path $tmp "source.zip"

Write-Host "==> 下载代码" -ForegroundColor Cyan
Write-Host "    $zipUrl" -ForegroundColor DarkGray
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

try {
    $ProgressPreference = "SilentlyContinue"      # 不显示进度条,快很多
    Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing
} catch {
    Write-Host ""
    Write-Warning "下载失败:$($_.Exception.Message)"
    Write-Host ""
    Write-Host "请改用浏览器手动下载,然后解压覆盖到 $repoRoot :" -ForegroundColor Yellow
    Write-Host "  $zipUrl" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "注意:要把解压出来那个长名字文件夹【里面的内容】覆盖进 $repoRoot," -ForegroundColor Yellow
    Write-Host "      而不是把整个文件夹丢进去。" -ForegroundColor Yellow
    exit 1
}

$sizeKb = [math]::Round((Get-Item $zipPath).Length / 1KB)
Write-Host "    下载完成($sizeKb KB)" -ForegroundColor DarkGray

Write-Host "==> 解压" -ForegroundColor Cyan
Expand-Archive -Path $zipPath -DestinationPath $tmp -Force
# ZIP 里是一个顶层长名字目录,取它下面的内容
$inner = Get-ChildItem -Path $tmp -Directory | Select-Object -First 1
if (-not $inner) {
    Write-Error "解压结果异常:没找到顶层目录"
    exit 1
}

Write-Host "==> 覆盖代码文件" -ForegroundColor Cyan
$copied = 0
$skipped = 0
Get-ChildItem -Path $inner.FullName -Recurse -File | ForEach-Object {
    $rel = $_.FullName.Substring($inner.FullName.Length + 1)
    $isProtected = $false
    foreach ($p in $protected) {
        if ($rel -eq $p -or $rel.StartsWith("$p\")) { $isProtected = $true; break }
    }
    if ($isProtected) {
        $skipped++
        return
    }
    $dest = Join-Path $repoRoot $rel
    $destDir = Split-Path -Parent $dest
    if (-not (Test-Path $destDir)) { New-Item -ItemType Directory -Path $destDir -Force | Out-Null }
    Copy-Item -Path $_.FullName -Destination $dest -Force
    $copied++
}
Write-Host "    覆盖 $copied 个文件" -ForegroundColor DarkGray
if ($skipped -gt 0) { Write-Host "    跳过 $skipped 个受保护文件" -ForegroundColor DarkGray }

if (-not $KeepDownload) {
    Remove-Item -Path $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "✅ 代码已更新" -ForegroundColor Green
Write-Host "   你的 config\pipeline.json、config\selection.txt、build\、notes\、.venv\ 都没有被动过。"
Write-Host ""

$py = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

if ($UpgradeConfig) {
    Write-Host "==> 补齐配置项" -ForegroundColor Cyan
    & $py -m nlnotes init --upgrade
} else {
    Write-Host "下一步:" -ForegroundColor Yellow
    Write-Host "  1) 补齐配置文件的新增项(保留你改过的值):"
    Write-Host "     .\.venv\Scripts\python.exe -m nlnotes init --upgrade" -ForegroundColor Cyan
}

if ($ReExtract) {
    Write-Host ""
    Write-Host "==> 重跑抽取(抽取阶段的改动才会生效)" -ForegroundColor Cyan
    & $py -m nlnotes extract --force
    & $py -m nlnotes tasks --force
} elseif (-not $UpgradeConfig) {
    Write-Host "  2) 如果本次改动涉及抽取阶段(噪声清理 / 图片参数 / OCR),重跑:"
    Write-Host "     .\.venv\Scripts\python.exe -m nlnotes extract --force" -ForegroundColor Cyan
    Write-Host "     .\.venv\Scripts\python.exe -m nlnotes tasks --force" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "     (tasks --force 不会动已写好的 OUTPUT\note.json)" -ForegroundColor DarkGray
}
