<#
    photo_guard.ps1 - PreToolUse フック

    写真原本ディレクトリ（D:\写真）に対する書き込み・削除・移動をブロックする。
    ファイル構成やメタデータの「読み取り」は参考情報として許可する。

    判定結果:
      exit 0 ... 許可（何も出力しない）
      exit 2 ... ブロック。stderr の内容がエージェントに返され、ツールは実行されない。

    対象ツール: Write / Edit / MultiEdit / NotebookEdit / Bash / PowerShell
    設定: .claude/settings.json の hooks.PreToolUse
#>

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { }

# ---------------------------------------------------------------------------
# 保護対象ルート（読み取りのみ許可。ここに追記すれば保護範囲を広げられる）
# ---------------------------------------------------------------------------
$ProtectedRoots = @(
    'D:\写真'
)

# 破壊的コマンド: この語より後ろ（次の | または ; まで）に保護パスが現れたらブロック
$DestructivePattern = '(?i)(Remove-Item|Move-Item|Rename-Item|Copy-Item|Set-Content|Add-Content|Clear-Content|New-Item|Out-File|Set-ItemProperty|Compress-Archive|Expand-Archive|robocopy|xcopy|\bdel\b|\berase\b|\brmdir\b|\brd\b|\brm\b|\bmv\b|\bcp\b|\bmkdir\b|\btouch\b|\btee\b|\battrib\b|\bicacls\b)'

# パイプで破壊的コマンドへ流し込む形: 保護パスがコマンド中のどこにあってもブロック。
# 「パイプ入力そのものに作用する」コマンドだけを列挙する。
# Out-File / Set-Content 等は出力先を引数で取るため、ここではなく $DestructivePattern（規則B）で判定する。
$PipeDestructivePattern = '(?i)\|\s*(Remove-Item|Move-Item|Rename-Item|Clear-Content|Set-ItemProperty|\bri\b|\brm\b|\bdel\b|\berase\b|\brd\b|\brmdir\b|\bmv\b|\bmove\b|\bmi\b|\bren\b|\brni\b)'


function Get-MentionPattern {
    # 保護ルートの言及を検出する正規表現を作る（\ と / の両表記、大小文字無視）
    param([string[]]$Roots)
    $alts = @()
    foreach ($r in $Roots) {
        $a = [regex]::Escape($r)
        $b = [regex]::Escape(($r -replace '\\', '/'))
        $alts += $a
        if ($b -ne $a) { $alts += $b }
    }
    return '(?i)(' + ($alts -join '|') + ')'
}

function Test-UnderProtected {
    # ファイルパスが保護ルート配下かどうか
    param([string]$Path, [string]$BaseDir)
    if ([string]::IsNullOrWhiteSpace($Path)) { return $false }
    try {
        if (-not [System.IO.Path]::IsPathRooted($Path) -and $BaseDir) {
            $Path = Join-Path $BaseDir $Path
        }
        $full = ([System.IO.Path]::GetFullPath($Path)).TrimEnd('\')
    } catch {
        return $false
    }
    foreach ($root in $ProtectedRoots) {
        $r = ([System.IO.Path]::GetFullPath($root)).TrimEnd('\')
        if ($full -ieq $r) { return $true }
        if ($full.StartsWith($r + '\', [System.StringComparison]::OrdinalIgnoreCase)) { return $true }
    }
    return $false
}

function Get-ArgumentRegion {
    # 指定位置から次のパイプ/セミコロンまでを「引数側」として切り出す
    param([string]$Command, [int]$Index)
    $rest = $Command.Substring($Index)
    $cut = $rest.IndexOfAny([char[]]@('|', ';'))
    if ($cut -gt 0) { $rest = $rest.Substring(0, $cut) }
    return $rest
}

function Test-CommandViolation {
    # シェルコマンド文字列を検査し、違反理由を返す（違反なしなら $null）
    param([string]$Command, [string]$MentionPattern)

    if ([string]::IsNullOrWhiteSpace($Command)) { return $null }
    if ($Command -notmatch $MentionPattern) { return $null }

    # (A) パイプ経由の破壊的コマンド（保護パスは上流にあるので位置判定できない）
    if ($Command -match $PipeDestructivePattern) {
        return "パイプ経由の破壊的コマンド `"$($Matches[0].Trim())`""
    }

    # (B) 破壊的コマンドの引数側に保護パスがある
    foreach ($m in [regex]::Matches($Command, $DestructivePattern)) {
        if ((Get-ArgumentRegion -Command $Command -Index $m.Index) -match $MentionPattern) {
            return "破壊的コマンド `"$($m.Value)`" の対象に保護パスが含まれる"
        }
    }

    # (C) リダイレクトの出力先が保護パス
    foreach ($m in [regex]::Matches($Command, '>>?')) {
        if ((Get-ArgumentRegion -Command $Command -Index $m.Index) -match $MentionPattern) {
            return "リダイレクトの出力先が保護パス"
        }
    }

    return $null
}


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
$raw = [Console]::In.ReadToEnd()
if ([string]::IsNullOrWhiteSpace($raw)) { exit 0 }
try { $payload = $raw | ConvertFrom-Json } catch { exit 0 }

$tool    = [string]$payload.tool_name
$ti      = $payload.tool_input
$cwd     = [string]$payload.cwd
$mention = Get-MentionPattern -Roots $ProtectedRoots
$reason  = $null

if ($tool -match '^(Write|Edit|MultiEdit|NotebookEdit)$') {
    $p = $ti.file_path
    if (-not $p) { $p = $ti.notebook_path }
    if (Test-UnderProtected -Path ([string]$p) -BaseDir $cwd) {
        $reason = "保護パス配下へのファイル書き込み: $p"
    }
}
elseif ($tool -match '^(Bash|PowerShell)$') {
    $reason = Test-CommandViolation -Command ([string]$ti.command) -MentionPattern $mention
}

if ($reason) {
    $roots = $ProtectedRoots -join ', '
    $msg = @"
[photo_guard] このツール呼び出しをブロックしました。

  検出内容 : $reason
  保護対象 : $roots

写真原本ディレクトリは「読み取り専用」です。再取得不可能なユーザー資産のため、
エージェントによる書き込み・削除・移動・リネームを禁止しています。

許可されている操作:
  - ファイル構成の確認 (Get-ChildItem / Glob / ls)
  - ファイル内容・メタデータの読み取り (Read / Get-Content / exiftool 等)

やりたいことが書き込みを伴う場合は、実行せずにユーザーへ確認してください。
検証用のファイル操作は必ずダミーデータ（tmp/ 配下等）に対して行ってください。
"@
    [Console]::Error.WriteLine($msg)
    exit 2
}

exit 0
