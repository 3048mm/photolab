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
    [switch]$StartMenu,
    # ログイン時に常駐（photolab watch）を起動する
    [switch]$Startup,
    # -Startup で作ったスタートアップ登録を外す
    [switch]$RemoveStartup
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
    param(
        [string]$Path,
        [string]$Command = 'gui',
        [string]$Description = 'Photolab - SD カードから写真を取り込む'
    )

    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($Path)
    $link.TargetPath = $pythonw
    $link.Arguments = "-m photolab $Command"
    $link.WorkingDirectory = $root
    $link.Description = $Description
    if (Test-Path $icon) { $link.IconLocation = $icon }
    $link.Save()

    Write-Host "作成: $Path"
    Write-Host "      $pythonw -m photolab $Command"
}

$startupLink = Join-Path ([Environment]::GetFolderPath('Startup')) 'Photolab 常駐.lnk'

if ($RemoveStartup) {
    if (Test-Path $startupLink) {
        Remove-Item $startupLink
        Write-Host "削除: $startupLink"
        Write-Host 'ログイン時の常駐を解除しました。'
    }
    else {
        Write-Host 'スタートアップ登録はありません。'
    }
    return
}

New-PhotolabShortcut -Path (Join-Path $root 'Photolab.lnk')

if ($Desktop) {
    New-PhotolabShortcut -Path (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Photolab.lnk')
}
if ($StartMenu) {
    New-PhotolabShortcut -Path (Join-Path ([Environment]::GetFolderPath('Programs')) 'Photolab.lnk')
}
if ($Startup) {
    # 常駐はタスクトレイに入る。カードを挿すと本体が開く
    New-PhotolabShortcut -Path $startupLink -Command 'watch' `
        -Description 'Photolab 常駐 - カードを挿すと取り込み画面を開く'
    Write-Host ''
    Write-Host '次回ログインから常駐します。今すぐ動かすなら:'
    Write-Host "  $pythonw -m photolab watch"
    Write-Host '解除するには -RemoveStartup を付けて実行してください。'
}

Write-Host ''
Write-Host '作業場所 : ' -NoNewline; Write-Host $root
