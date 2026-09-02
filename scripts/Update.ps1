<#
.SYNOPSIS
    Update nlnotes code without git (for networks that break git TLS).

.DESCRIPTION
    Downloads the branch ZIP from GitHub and overlays code files.
    Never touches: config\pipeline.json, config\selection.txt, build\, notes\, .venv\

    Download order: Invoke-WebRequest (TLS 1.2) then curl.exe --ssl-no-revoke.
    If both fail, download the ZIP in a browser and pass -ZipPath (no manual unzip).

    This file is ASCII-only so Windows PowerShell 5.1 can parse it even without a BOM.

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
    Write-Host "Auto download failed (corporate TLS intercept)." -ForegroundColor Red
    Write-Host "Download the ZIP in your browser, then run (do not unzip by hand):" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  $zipUrl" -ForegroundColor Cyan
    Write-Host ""
    Write-Host '  .\scripts\Update.ps1 -ZipPath "$env:USERPROFILE\Downloads\the-file.zip" -UpgradeConfig' -ForegroundColor Cyan
    Write-Host ""
}

if ($ZipPath -ne "") {
    if (-not (Test-Path -LiteralPath $ZipPath)) {
        Write-Host "ZIP not found: $ZipPath" -ForegroundColor Red
        exit 1
    }
    Write-Host "==> using local ZIP" -ForegroundColor Cyan
    Write-Host "    $ZipPath" -ForegroundColor DarkGray
    Copy-Item -LiteralPath $ZipPath -Destination $zipFile -Force
}
else {
    Write-Host "==> download" -ForegroundColor Cyan
    Write-Host "    $zipUrl" -ForegroundColor DarkGray
    $ProgressPreference = "SilentlyContinue"
    $ok = $false

    try {
        [Net.ServicePointManager]::SecurityProtocol = 3072
    }
    catch {
        Write-Host "    (could not force TLS 1.2, continuing)" -ForegroundColor DarkGray
    }

    try {
        Invoke-WebRequest -Uri $zipUrl -OutFile $zipFile -UseBasicParsing
        if ((Test-Path $zipFile) -and ((Get-Item $zipFile).Length -gt 10000)) {
            $ok = $true
        }
    }
    catch {
        Write-Host "    Invoke-WebRequest failed: $($_.Exception.Message)" -ForegroundColor DarkYellow
    }

    if (-not $ok) {
        $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
        if ($curl) {
            Write-Host "    retry with curl.exe --ssl-no-revoke" -ForegroundColor DarkYellow
            & $curl.Source --ssl-no-revoke -L --fail -sS -o $zipFile $zipUrl
            if (($LASTEXITCODE -eq 0) -and (Test-Path $zipFile) -and ((Get-Item $zipFile).Length -gt 10000)) {
                $ok = $true
            }
        }
    }

    if (-not $ok) {
        Show-ManualSteps
        Remove-Item -Path $tmp -Recurse -Force -ErrorAction SilentlyContinue
        exit 1
    }
}

$sizeKb = [math]::Round((Get-Item $zipFile).Length / 1KB)
Write-Host "    ready $sizeKb KB" -ForegroundColor DarkGray

Write-Host "==> unzip" -ForegroundColor Cyan
Expand-Archive -Path $zipFile -DestinationPath $tmp -Force
$inner = Get-ChildItem -Path $tmp -Directory | Select-Object -First 1
if ($null -eq $inner) {
    Write-Host "unzip failed: no top-level folder" -ForegroundColor Red
    exit 1
}

Write-Host "==> overlay code" -ForegroundColor Cyan
$rcArgs = @(
    $inner.FullName, $repoRoot,
    "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP",
    "/XF", "pipeline.json", "pipeline.json.bak", "selection.txt",
    "/XD", "build", "notes", "out", ".venv"
)
& robocopy @rcArgs | Out-Null
if ($LASTEXITCODE -ge 8) {
    Write-Host "copy failed (robocopy exit $LASTEXITCODE)" -ForegroundColor Red
    exit 1
}
Write-Host "    done" -ForegroundColor DarkGray

if (-not $KeepDownload) {
    Remove-Item -Path $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "code updated" -ForegroundColor Green
Write-Host "left untouched: config\pipeline.json, config\selection.txt, build\, notes\, .venv\"
Write-Host ""

$py = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    $py = "python"
}

if ($UpgradeConfig) {
    Write-Host "==> upgrade config" -ForegroundColor Cyan
    & $py -m nlnotes init --upgrade
}
else {
    Write-Host "next:" -ForegroundColor Yellow
    Write-Host "  .\.venv\Scripts\python.exe -m nlnotes init --upgrade" -ForegroundColor Cyan
}

if ($ReExtract) {
    Write-Host ""
    Write-Host "==> re-extract" -ForegroundColor Cyan
    & $py -m nlnotes extract --force
    & $py -m nlnotes tasks --force
}
elseif (-not $UpgradeConfig) {
    Write-Host "  if extract/OCR/noise-filter changed:" -ForegroundColor Yellow
    Write-Host "     .\.venv\Scripts\python.exe -m nlnotes extract --force" -ForegroundColor Cyan
    Write-Host "     .\.venv\Scripts\python.exe -m nlnotes tasks --force" -ForegroundColor Cyan
    Write-Host "     (tasks --force keeps OUTPUT\note.json)" -ForegroundColor DarkGray
}
