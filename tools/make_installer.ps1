#Requires -Version 5.1
<#
.SYNOPSIS
    インストーラー（setup.exe）を作る。

.DESCRIPTION
    Inno Setup で dist\Photolab-<版>-setup.exe を作る。
    先に tools\build.ps1 で dist\Photolab\ を作っておくこと。

    Inno Setup の導入:  winget install JRSoftware.InnoSetup

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\make_installer.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\make_installer.ps1 -Version 0.2.0
#>
[CmdletBinding()]
param(
    # 版。既定は photolab/__init__.py の __version__
    [string]$Version,
    # 配置版のある場所。既定は dist\
    [string]$DistPath
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot

$dist = if ($DistPath) {
    if ([System.IO.Path]::IsPathRooted($DistPath)) { $DistPath } else { Join-Path $root $DistPath }
} else {
    Join-Path $root 'dist'
}
$bundle = Join-Path $dist 'Photolab'

if (-not (Test-Path (Join-Path $bundle 'Photolab.exe'))) {
    throw "配置版がありません: $bundle`n先に tools\build.ps1 を実行してください。"
}

# 版は photolab/__init__.py の __version__ を正とする
if (-not $Version) {
    $initFile = Join-Path $root 'photolab\__init__.py'
    $match = Select-String -Path $initFile -Pattern '__version__\s*=\s*"([^"]+)"'
    if (-not $match) { throw "__version__ を $initFile から読めません" }
    $Version = $match.Matches[0].Groups[1].Value
}
Write-Host "版: $Version"

# winget はユーザー領域に入れることがある。system / user の両方を見る
$iscc = @(
    'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
    'C:\Program Files\Inno Setup 6\ISCC.exe',
    (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $iscc) {
    throw "Inno Setup が見つかりません。`n導入するには:  winget install JRSoftware.InnoSetup"
}

Write-Host "コンパイラ: $iscc"
Write-Host ''

& $iscc "/DAppVersion=$Version" "/DSourceDir=$bundle" "/DOutDir=$dist" `
    (Join-Path $root 'installer\photolab.iss')
if ($LASTEXITCODE -ne 0) { throw 'Inno Setup が失敗しました。' }

$setup = Join-Path $dist "Photolab-$Version-setup.exe"
if (Test-Path $setup) {
    Write-Host ''
    Write-Host ("完成: {0}  ({1:N1} MB)" -f $setup, ((Get-Item $setup).Length / 1MB))
}
