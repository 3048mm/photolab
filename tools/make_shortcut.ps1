#Requires -Version 5.1
<#
.SYNOPSIS
    Photolab を起動するショートカットを作る。

.DESCRIPTION
    venv の pythonw.exe を直接指すショートカットを作る。
    pythonw なのでコンソール窓が出ず、アイコンも Photolab のものになる。

    .bat を経由しないのは、経由すると黒い窓が一瞬出るため。

    生成物は環境固有の絶対パスを含むので git 管理しない（.gitignore 済み）。

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\make_shortcut.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\make_shortcut.ps1 -Desktop -StartMenu
#>
[CmdletBinding()]
param(
    # デスクトップにも置く
    [switch]$Desktop,
    # スタートメニューにも置く
    [switch]$StartMenu
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $root 'venv\Scripts\pythonw.exe'
$icon = Join-Path $root 'photolab\ui\assets\photolab.ico'

if (-not (Test-Path $pythonw)) {
    throw "pythonw.exe が見つかりません: $pythonw`n先に venv を作ってください。"
}
if (-not (Test-Path $icon)) {
    Write-Warning "アイコンが見つかりません: $icon（既定のアイコンになります）"
}

function New-PhotolabShortcut {
    param([string]$Path)

    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($Path)
    $link.TargetPath = $pythonw
    $link.Arguments = '-m photolab gui'
    $link.WorkingDirectory = $root
    $link.Description = 'Photolab - SD カードから写真を取り込む'
    if (Test-Path $icon) { $link.IconLocation = $icon }
    $link.Save()

    Write-Host "作成: $Path"
}

$targets = @(Join-Path $root 'Photolab.lnk')
if ($Desktop) {
    $targets += Join-Path ([Environment]::GetFolderPath('Desktop')) 'Photolab.lnk'
}
if ($StartMenu) {
    $programs = [Environment]::GetFolderPath('Programs')
    $targets += Join-Path $programs 'Photolab.lnk'
}

foreach ($target in $targets) {
    New-PhotolabShortcut -Path $target
}

Write-Host ''
Write-Host '起動対象 : ' -NoNewline; Write-Host $pythonw
Write-Host '引数     : -m photolab gui'
Write-Host '作業場所 : ' -NoNewline; Write-Host $root
