#Requires -Version 5.1
<#
.SYNOPSIS
    配布用のインストーラーを作る。

.DESCRIPTION
    1. テストを走らせる（壊れたものを配らないため）
    2. PyInstaller で dist\Photolab\ を作る（onedir）
    3. Inno Setup で dist\Photolab-<版>-setup.exe を作る

    Inno Setup が無ければ 2 まで行って止まる。
    導入は: winget install JRSoftware.InnoSetup

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\build.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\build.ps1 -SkipTests
#>
[CmdletBinding()]
param(
    [switch]$SkipTests,
    [string]$Version,
    # 出力先。既定は dist。前回の出力を掴んでいるプロセスがあるときに逃がせる
    [string]$DistPath
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root 'venv\Scripts\python.exe'
$pyinstaller = Join-Path $root 'venv\Scripts\pyinstaller.exe'
$dist = if ($DistPath) {
    if ([System.IO.Path]::IsPathRooted($DistPath)) { $DistPath } else { Join-Path $root $DistPath }
} else {
    Join-Path $root 'dist'
}

if (-not (Test-Path $python)) { throw "venv がありません: $python" }
if (-not (Test-Path $pyinstaller)) {
    throw "PyInstaller がありません。`n  $python -m pip install -r requirements-dev.txt"
}

# 版は photolab/__init__.py の __version__ を正とする
if (-not $Version) {
    $initFile = Join-Path $root 'photolab\__init__.py'
    $match = Select-String -Path $initFile -Pattern '__version__\s*=\s*"([^"]+)"'
    if (-not $match) { throw "__version__ を $initFile から読めません" }
    $Version = $match.Matches[0].Groups[1].Value
}
Write-Host "版: $Version"

# --- 1. テスト ---------------------------------------------------------
if (-not $SkipTests) {
    Write-Host ''
    Write-Host '=== テスト ==='
    $env:PYTHONIOENCODING = 'utf-8'
    $env:PYTHONUTF8 = '1'
    & $python -m pytest (Join-Path $root 'tests') -q
    if ($LASTEXITCODE -ne 0) { throw 'テストが失敗しました。配布物は作りません。' }
}

# --- 2. PyInstaller ----------------------------------------------------
Write-Host ''
Write-Host '=== PyInstaller (onedir) ==='
& $pyinstaller (Join-Path $root 'photolab.spec') --noconfirm `
    --distpath $dist --workpath (Join-Path $root 'build')
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller が失敗しました。' }

$bundle = Join-Path $dist 'Photolab'
$size = (Get-ChildItem $bundle -Recurse -File | Measure-Object -Property Length -Sum).Sum
Write-Host ("出力: {0}  ({1:N1} MB)" -f $bundle, ($size / 1MB))

# GPL のものが混ざっていないか確認する（配布物に入れてはならない）
$forbidden = Get-ChildItem $bundle -Recurse -File | Where-Object { $_.Name -match 'exiv2' }
if ($forbidden) {
    $forbidden | ForEach-Object { Write-Warning "GPL の依存が混入: $($_.FullName)" }
    throw '配布物に GPL の依存が入っています。photolab.spec の excludes を見直してください。'
}
Write-Host 'GPL 依存の混入なし。'

# --- 3. Inno Setup -----------------------------------------------------
# winget はユーザー領域に入れることがある。system / user の両方を見る
$iscc = @(
    'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
    'C:\Program Files\Inno Setup 6\ISCC.exe',
    (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $iscc) {
    Write-Host ''
    Write-Warning 'Inno Setup が見つかりません。インストーラーは作れません。'
    Write-Host '導入するには:  winget install JRSoftware.InnoSetup'
    Write-Host "配置版はできています: $bundle"
    return
}

Write-Host ''
Write-Host '=== Inno Setup ==='
& $iscc "/DAppVersion=$Version" "/DSourceDir=$bundle" "/DOutDir=$dist" `
    (Join-Path $root 'installer\photolab.iss')
if ($LASTEXITCODE -ne 0) { throw 'Inno Setup が失敗しました。' }

$setup = Join-Path $dist "Photolab-$Version-setup.exe"
if (Test-Path $setup) {
    $mb = [math]::Round((Get-Item $setup).Length / 1MB, 1)
    Write-Host ''
    Write-Host "完成: $setup  ($mb MB)"
}
