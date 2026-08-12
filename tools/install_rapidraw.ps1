#Requires -Version 5.1
<#
.SYNOPSIS
    RapidRAW を公式リリースから取得してインストールする。

.DESCRIPTION
    Photolab は RapidRAW を同梱しない。RapidRAW は AGPL-3.0 であり、
    再配布すると義務が発生する。公式の GitHub Releases から取得するだけなら
    その義務は生じない。

    既定では「何をどこから取るか」を表示して確認を求める。
    -Yes を付けると確認なしで進む（インストーラーからの自動実行用）。

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\install_rapidraw.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\install_rapidraw.ps1 -Yes
#>
[CmdletBinding()]
param(
    [switch]$Yes,          # 確認せずに進む
    [switch]$DownloadOnly  # ダウンロードだけして実行しない
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest を速くする

$repo = 'CyberTimon/RapidRAW'
$api = "https://api.github.com/repos/$repo/releases/latest"
$installed = Join-Path $env:LOCALAPPDATA 'RapidRAW\RapidRAW.exe'

if (Test-Path $installed) {
    Write-Host "RapidRAW は既に入っています: $installed"
    return
}

Write-Host "最新リリースを問い合わせています: $api"
try {
    $release = Invoke-RestMethod -Uri $api -Headers @{ 'User-Agent' = 'Photolab' }
}
catch {
    Write-Warning "リリース情報を取得できませんでした: $($_.Exception.Message)"
    Write-Host "手動で入れる場合: https://github.com/$repo/releases"
    return
}

# CPU に合わせて資産を選ぶ
$pattern = if ($env:PROCESSOR_ARCHITECTURE -match 'ARM') {
    '_windows-11-arm_arm64\.exe$'
} else {
    '_windows_x64\.exe$'
}
$asset = $release.assets | Where-Object { $_.name -match $pattern } | Select-Object -First 1
if (-not $asset) {
    Write-Warning "この環境向けのインストーラーが見つかりません（$pattern）"
    return
}

# 取得元が公式であることを確かめる。別ホストへ誘導されていたら止める
if ($asset.browser_download_url -notmatch "^https://github\.com/$repo/releases/download/") {
    throw "想定外のダウンロード元です: $($asset.browser_download_url)"
}

Write-Host ''
Write-Host "バージョン : $($release.tag_name)"
Write-Host "ファイル   : $($asset.name)  ($([math]::Round($asset.size / 1MB, 1)) MB)"
Write-Host "取得元     : $($asset.browser_download_url)"
Write-Host 'ライセンス : AGPL-3.0（Photolab とは別のソフトです）'
Write-Host ''

if (-not $Yes) {
    if ((Read-Host 'ダウンロードしてインストールしますか？ [y/N]') -notmatch '^[yY]') {
        Write-Host '中止しました。'
        return
    }
}

$destination = Join-Path $env:TEMP $asset.name
Write-Host "ダウンロード中..."
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $destination -UseBasicParsing

# 途中で切れたものを実行しないよう、サイズを照合する
$actual = (Get-Item $destination).Length
if ($actual -ne $asset.size) {
    Remove-Item $destination -Force
    throw "サイズが一致しません（期待 $($asset.size) / 実際 $actual）。中断しました。"
}
Write-Host "ダウンロード完了: $([math]::Round($actual / 1MB, 1)) MB"

if ($DownloadOnly) {
    Write-Host "実行はしません: $destination"
    return
}

Write-Host 'インストーラーを実行します...'
$process = Start-Process -FilePath $destination -Wait -PassThru
Write-Host "インストーラーの終了コード: $($process.ExitCode)"
Remove-Item $destination -Force -ErrorAction SilentlyContinue

if (Test-Path $installed) {
    Write-Host "完了: $installed"
    Write-Host 'Photolab の［現像］で RapidRAW を選べます。'
}
else {
    Write-Warning '既定の場所に見つかりません。別の場所に入れた場合は Photolab の設定でパスを指定してください。'
}
