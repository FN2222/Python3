<#
.SYNOPSIS
    一键更新 nlnotes 代码(不依赖 git,适合公司网络下 git 报证书错误的情况)

.DESCRIPTION
    从 GitHub 下载分支 ZIP 并覆盖本地代码文件,自动跳过你的配置与产物:
      不会被动到:config\pipeline.json、config\selection.txt、build\、notes\、.venv\

    自动下载会依次尝试:启用 TLS 1.2/1.3 的 Invoke-WebRequest、
    curl.exe --ssl-no-revoke。公司网络拦得厉害时两条都会失败,
    此时改用浏览器下载 ZIP,再用 -ZipPath 把它交给本脚本(不用你手工解压)。

.NOTES
    第一次用不了这个脚本?说明你本地的代码还没有它(脚本没法更新到包含它自己的版本)。
    先按 docs/08-本机上手-用Cursor跑.md 里的「首次自助更新」拉一次。

.EXAMPLE
    .\scripts\Update.ps1 -UpgradeConfig

.EXAMPLE
    .\scripts\Update.ps1 -ZipPath "$env:USERPROFILE\Downloads\Python3-cursor-xxx.zip" -UpgradeConfig
#>
[CmdletBinding()]
param(
    [string]$Branch = "cursor/networklessons-pdf-to-chinese-notes-pipeline-ec2b",
    [string]$Repo = "FN2222/Python3",
    [string]$ZipPath = "",
    [switch]$UpgradeConfig,
    [switch]$ReExtract,
    [switch]$KeepDownload
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$zipUrl = "https://github.com/$Repo/archive/refs/heads/$Branch.zip"
$tmp = Join-Path $env:TEMP ("nlnotes-update-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
$zipFile = Join-Path $tmp "source.zip"
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

function Show-ManualSteps {
    Write-Host ""
    Write-Host "改用浏览器下载,然后把 ZIP 直接交给本脚本(不用手工解压):" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  1) 浏览器打开并下载:" -ForegroundColor Yellow
    Write-Host "     $zipUrl" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  2) 然后执行(把路径换成你实际的下载位置):" -ForegroundColor Yellow
    Write-Host '     .\scripts\Update.ps1 -ZipPath "$env:USERPROFILE\Downloads\你下载的.zip" -UpgradeConfig' -ForegroundColor Cyan
    Write-Host ""
}

# ---------------------------------------------------------------- 取得 ZIP

if ($ZipPath -ne "") {
    if (-not (Test-Path $ZipPath)) {
        Write-Host "找不到指定的 ZIP: $ZipPath" -ForegroundColor Red
        exit 1
    }
    Write-Host "==> 使用本地 ZIP" -ForegroundColor Cyan
    Write-Host "    $ZipPath" -ForegroundColor DarkGray
    Copy-Item -Path $ZipPath -Destination $zipFile -Force
}
else {
    Write-Host "==> 下载代码" -ForegroundColor Cyan
    Write-Host "    $zipUrl" -ForegroundColor DarkGray
    $ProgressPreference = "SilentlyContinue"
    $ok = $false

    try {
        [Net.ServicePointManager]::SecurityProtocol = 3072
    }
    catch {
        Write-Host "    (无法设置 TLS 1.2,继续尝试)" -ForegroundColor DarkGray
    }

    try {
        Invoke-WebRequest -Uri $zipUrl -OutFile $zipFile -UseBasicParsing
        $ok = $true
    }
    catch {
        $msg = $_.Exception.Message
        Write-Host "    Invoke-WebRequest 失败: $msg" -ForegroundColor DarkYellow
    }

    if (-not $ok) {
        $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
        if ($curl) {
            Write-Host "    改用 curl.exe --ssl-no-revoke 重试" -ForegroundColor DarkYellow
            & $curl.Source --ssl-no-revoke -sSL -o $zipFile $zipUrl
            if (($LASTEXITCODE -eq 0) -and (Test-Path $zipFile)) {
                $ok = $true
            }
        }
    }

    if (-not $ok) {
        Write-Host ""
        Write-Host "自动下载失败(公司网络的 TLS 拦截)。" -ForegroundColor Red
        Show-ManualSteps
        Remove-Item -Path $tmp -Recurse -Force -ErrorAction SilentlyContinue
        exit 1
    }
}

$sizeKb = [math]::Round((Get-Item $zipFile).Length / 1KB)
Write-Host "    就绪 ($sizeKb KB)" -ForegroundColor DarkGray

# ---------------------------------------------------------------- 解压并覆盖

Write-Host "==> 解压" -ForegroundColor Cyan
Expand-Archive -Path $zipFile -DestinationPath $tmp -Force
$inner = Get-ChildItem -Path $tmp -Directory | Select-Object -First 1
if ($null -eq $inner) {
    Write-Host "解压结果异常: 没找到顶层目录" -ForegroundColor Red
    exit 1
}

Write-Host "==> 覆盖代码文件" -ForegroundColor Cyan
# 用 robocopy 而不是 Copy-Item: 目标目录已存在时 Copy-Item -Recurse 可能嵌套一层。
# 没有用 /MIR,所以不会删除本地多出来的文件。
$rcArgs = @(
    $inner.FullName, $repoRoot,
    "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP",
    "/XF", "pipeline.json", "pipeline.json.bak", "selection.txt",
    "/XD", "build", "notes", "out", ".venv"
)
& robocopy @rcArgs | Out-Null
if ($LASTEXITCODE -ge 8) {
    Write-Host "复制失败 (robocopy 退出码 $LASTEXITCODE)" -ForegroundColor Red
    exit 1
}
Write-Host "    完成" -ForegroundColor DarkGray

if (-not $KeepDownload) {
    Remove-Item -Path $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "代码已更新" -ForegroundColor Green
Write-Host "你的 config\pipeline.json、config\selection.txt、build\、notes\、.venv\ 都没有被动过。"
Write-Host ""

# ---------------------------------------------------------------- 后续步骤

$py = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    $py = "python"
}

if ($UpgradeConfig) {
    Write-Host "==> 补齐配置项" -ForegroundColor Cyan
    & $py -m nlnotes init --upgrade
}
else {
    Write-Host "下一步:" -ForegroundColor Yellow
    Write-Host "  1) 补齐配置文件的新增项(保留你改过的值):" -ForegroundColor Yellow
    Write-Host "     .\.venv\Scripts\python.exe -m nlnotes init --upgrade" -ForegroundColor Cyan
}

if ($ReExtract) {
    Write-Host ""
    Write-Host "==> 重跑抽取" -ForegroundColor Cyan
    & $py -m nlnotes extract --force
    & $py -m nlnotes tasks --force
}
elseif (-not $UpgradeConfig) {
    Write-Host "  2) 若本次改动涉及抽取阶段(噪声清理/图片参数/OCR),重跑:" -ForegroundColor Yellow
    Write-Host "     .\.venv\Scripts\python.exe -m nlnotes extract --force" -ForegroundColor Cyan
    Write-Host "     .\.venv\Scripts\python.exe -m nlnotes tasks --force" -ForegroundColor Cyan
    Write-Host "     (tasks --force 不会动已写好的 OUTPUT\note.json)" -ForegroundColor DarkGray
}
