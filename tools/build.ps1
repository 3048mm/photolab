#Requires -Version 5.1
<#
.SYNOPSIS
    配置版（onedir）をビルドする。

.DESCRIPTION
    テストを走らせてから PyInstaller で dist\Photolab\ を作る。
    インストーラーを作るのは tools\make_installer.ps1（分けてある）。

    onedir にしているのは、onefile だと起動のたびに 160MB を展開して遅く、
    PySide6 (LGPLv3) の Qt DLL を差し替え可能な状態に保てないため。

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\build.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\build.ps1 -SkipTests
#>
[CmdletBinding()]
param(
    # テストを飛ばす（普段は付けない）
    [switch]$SkipTests,
    # 出力先。既定は dist\
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

# --- テスト -----------------------------------------------------------
if (-not $SkipTests) {
    Write-Host '=== テスト ==='
    $env:PYTHONIOENCODING = 'utf-8'
    $env:PYTHONUTF8 = '1'
    & $python -m pytest (Join-Path $root 'tests') -q
    if ($LASTEXITCODE -ne 0) { throw 'テストが失敗しました。配布物は作りません。' }
    Write-Host ''
}

# --- PyInstaller ------------------------------------------------------
Write-Host '=== PyInstaller (onedir) ==='
& $pyinstaller (Join-Path $root 'photolab.spec') --noconfirm `
    --distpath $dist --workpath (Join-Path $root 'build')
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller が失敗しました。' }

$bundle = Join-Path $dist 'Photolab'
$size = (Get-ChildItem $bundle -Recurse -File | Measure-Object -Property Length -Sum).Sum
Write-Host ''
Write-Host ("出力: {0}  ({1:N1} MB)" -f $bundle, ($size / 1MB))

# --- 配布物に GPL の依存が混ざっていないか ------------------------------
# pyexiv2 / exiv2 は開発時の答え合わせ専用（NOTICE.md）。入れてはならない
$forbidden = Get-ChildItem $bundle -Recurse -File | Where-Object { $_.Name -match 'exiv2' }
if ($forbidden) {
    $forbidden | ForEach-Object { Write-Warning "GPL の依存が混入: $($_.FullName)" }
    throw '配布物に GPL の依存が入っています。photolab.spec の excludes を見直してください。'
}
Write-Host 'GPL 依存の混入なし。'

Write-Host ''
Write-Host 'インストーラーを作るには:'
Write-Host '  powershell -NoProfile -ExecutionPolicy Bypass -File tools\make_installer.ps1'
