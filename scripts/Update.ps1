<#
.SYNOPSIS
    一键更新 nlnotes 代码(不依赖 git,适合公司网络下 git 报证书错误的情况)

.DESCRIPTION
    从 GitHub 下载分支 ZIP 并覆盖本地代码文件,自动跳过你的配置与产物:
      不会被动到:config\pipeline.json、config\selection.txt、build\、notes\、.venv\
    下载用的是 PowerShell 的 Invoke-WebRequest,走 Windows 证书存储 ——
    浏览器能访问 GitHub,它一般就能下载成功(而 git 的 schannel 可能因为
    吊销检查失败而报 SEC_E_UNTRUSTED_ROOT)。

.NOTES
    第一次用不了这个脚本?说明你本地的代码还没有它(脚本没法更新到"包含它自己"的版本)。
    先用 docs/08-本机上手-用Cursor跑.md 里的"首次自助更新"那段命令拉一次,
    之后就能一直用这个脚本了。

.EXAMPLE
    .\scripts\Update.ps1

.EXAMPLE
    # 更新后顺手补齐配置项并重跑抽取
    .\scripts\Update.ps1 -UpgradeConfig -ReExtract

.EXAMPLE
    # 公司网络拦 TLS、自动下载失败时:浏览器下好 ZIP,直接交给脚本处理
    .\scripts\Update.ps1 -ZipPath "$env:USERPROFILE\Downloads\Python3-cursor-xxx.zip" -UpgradeConfig
#>
[CmdletBinding()]
param(
    [string]$Branch = "cursor/networklessons-pdf-to-chinese-notes-pipeline-ec2b",
    [string]$Repo = "FN2222/Python3",
    [string]$ZipPath,
    [switch]$UpgradeConfig,
    [switch]$ReExtract,
    [switch]$KeepDownload
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

# 你的配置与产物永远不会被覆盖:它们本来就不在 ZIP 里(被 .gitignore 排除),
# 下面复制时还会用 robocopy 的 /XF /XD 再排除一次,双重保险。

$zipUrl = "https://github.com/$Repo/archive/refs/heads/$Branch.zip"
$tmp = Join-Path $env:TEMP ("nlnotes-update-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
$zipPath = Join-Path $tmp "source.zip"

New-Item -ItemType Directory -Path $tmp -Force | Out-Null

if ($ZipPath) {
    # 手动下载好的 ZIP:跳过下载,直接用它(公司网络拦 TLS 时最省事的路子)
    if (-not (Test-Path $ZipPath)) {
        Write-Error "找不到指定的 ZIP: $ZipPath"
        exit 1
    }
    Write-Host "==> 使用本地 ZIP" -ForegroundColor Cyan
    Write-Host "    $ZipPath" -ForegroundColor DarkGray
    Copy-Item -Path $ZipPath -Destination $zipPath -Force
} else {
    Write-Host "==> 下载代码" -ForegroundColor Cyan
    Write-Host "    $zipUrl" -ForegroundColor DarkGray
    $ProgressPreference = "SilentlyContinue"      # 不显示进度条,快很多

    # 公司网络常见两类问题,所以按三条路依次尝试:
    #   1. .NET 默认协议偏旧 -> 显式启用 TLS 1.2/1.3
    #   2. 中间设备换证书导致吊销检查失败 -> curl.exe --ssl-no-revoke(绕过吊销检查)
    #   3. 都不行 -> 让用户浏览器下载后用 -ZipPath 传进来
    $ok = $false
    try {
        [Net.ServicePointManager]::SecurityProtocol = 3072 -bor 12288   # Tls12 | Tls13
    } catch {
        try { [Net.ServicePointManager]::SecurityProtocol = 3072 } catch { }
    }
    try {
        Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing
        $ok = $true
    } catch {
        Write-Host "    Invoke-WebRequest 失败:$($_.Exception.Message)" -ForegroundColor DarkYellow
    }

    if (-not $ok) {
        $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
        if ($curl) {
            Write-Host "    改用 curl.exe --ssl-no-revoke 重试" -ForegroundColor DarkYellow
            & $curl.Source --ssl-no-revoke -sSL -o $zipPath $zipUrl
            if ($LASTEXITCODE -eq 0 -and (Test-Path $zipPath)) { $ok = $true }
        }
    }

    if (-not $ok) {
        Write-Host ""
        Write-Warning "自动下载失败(公司网络的 TLS 拦截)。"
        Write-Host ""
        Write-Host "改用浏览器下载,然后把 ZIP 直接交给本脚本 —— 不用你手工解压:" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "  1) 浏览器打开并下载:" -ForegroundColor Yellow
        Write-Host "     $zipUrl" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "  2) 然后执行(路径换成你实际的下载位置):" -ForegroundColor Yellow
        Write-Host "     .\scripts\Update.ps1 -ZipPath `"`$env:USERPROFILE\Downloads\Python3-cursor-$($Branch.Split('/')[-1]).zip`" -UpgradeConfig" -ForegroundColor Cyan
        Write-Host ""
        Remove-Item -Path $tmp -Recurse -Force -ErrorAction SilentlyContinue
        exit 1
    }
}

$sizeKb = [math]::Round((Get-Item $zipPath).Length / 1KB)
Write-Host "    就绪($sizeKb KB)" -ForegroundColor DarkGray

Write-Host "==> 解压" -ForegroundColor Cyan
Expand-Archive -Path $zipPath -DestinationPath $tmp -Force
# ZIP 里是一个顶层长名字目录,取它下面的内容
$inner = Get-ChildItem -Path $tmp -Directory | Select-Object -First 1
if (-not $inner) {
    Write-Error "解压结果异常:没找到顶层目录"
    exit 1
}

Write-Host "==> 覆盖代码文件" -ForegroundColor Cyan
# 用 robocopy 而不是 Copy-Item:目标目录已存在时 Copy-Item -Recurse 有可能嵌套一层,
# robocopy 是专门做目录合并的,而且能用 /XF /XD 精确排除。
# 注意没有用 /MIR —— 不会删除本地多出来的文件(比如你的产物目录)。
$excludeFiles = @("pipeline.json", "pipeline.json.bak", "selection.txt")
$excludeDirs = @("build", "notes", "out", ".venv")
$rcArgs = @($inner.FullName, $repoRoot, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP")
$rcArgs += "/XF"; $rcArgs += $excludeFiles
$rcArgs += "/XD"; $rcArgs += $excludeDirs
& robocopy @rcArgs | Out-Null
# robocopy 的退出码 0-7 都算成功(8 及以上才是真失败)
if ($LASTEXITCODE -ge 8) {
    Write-Error "复制失败(robocopy 退出码 $LASTEXITCODE)"
    exit 1
}
Write-Host "    完成(已跳过 $($excludeFiles -join '、') 与 $($excludeDirs -join '、'))" `
    -ForegroundColor DarkGray

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
