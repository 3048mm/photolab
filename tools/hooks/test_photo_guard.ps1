<#
    test_photo_guard.ps1 - photo_guard.ps1 の回帰テスト

    実行:  powershell -NoProfile -File tools\hooks\test_photo_guard.ps1

    photo_guard.ps1 を編集したら必ず実行すること。
    Edit / Write ツールでの編集は UTF-8 BOM を落とし、Windows PowerShell 5.1 が
    スクリプトを CP932 として読むためパス比較が静かに失敗する（＝ガードが無効化される）。
    本テストは BOM の有無もチェックする。
    詳細: doc/agent_execution_rules.md §2
#>

$ErrorActionPreference = 'Stop'
$root  = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$guard = Join-Path $PSScriptRoot 'photo_guard.ps1'
$fail  = 0

# --- 0. BOM チェック（これが落ちると他のテストも道連れで落ちる） ---
$head = [System.IO.File]::ReadAllBytes($guard)[0..2]
if ($head[0] -eq 239 -and $head[1] -eq 187 -and $head[2] -eq 191) {
    "OK   00 photo_guard.ps1 は UTF-8 BOM 付き"
} else {
    "FAIL 00 photo_guard.ps1 に BOM がない -> 日本語パスの比較が壊れる。BOM を付け直すこと"
    $fail++
}

$cases = @(
    @{ n = '01 Write 保護配下';         expect = 'BLOCK'; tool = 'Write';      inp = @{ file_path = 'D:\写真\Z6\memo.txt' } },
    @{ n = '02 Write プロジェクト内';    expect = 'ALLOW'; tool = 'Write';      inp = @{ file_path = 'D:\My Documents\Programing\Photolab\photolab\a.py' } },
    @{ n = '03 Edit 相対パス';           expect = 'ALLOW'; tool = 'Edit';       inp = @{ file_path = 'photolab\b.py' } },
    @{ n = '04 一覧取得';               expect = 'ALLOW'; tool = 'PowerShell'; inp = @{ command = 'Get-ChildItem "D:\写真\Z6" -Force' } },
    @{ n = '05 Remove-Item 直接';       expect = 'BLOCK'; tool = 'PowerShell'; inp = @{ command = 'Remove-Item "D:\写真\Z6\test" -Recurse -Force' } },
    @{ n = '06 パイプで Remove-Item';   expect = 'BLOCK'; tool = 'PowerShell'; inp = @{ command = 'Get-ChildItem "D:\写真" -Recurse | Remove-Item' } },
    @{ n = '07 Out-File は外部へ';      expect = 'ALLOW'; tool = 'PowerShell'; inp = @{ command = 'Get-ChildItem "D:\写真" | Out-File list.txt' } },
    @{ n = '08 リダイレクト外部へ';      expect = 'ALLOW'; tool = 'PowerShell'; inp = @{ command = 'Get-ChildItem D:\写真 > list.txt' } },
    @{ n = '09 リダイレクト保護先へ';    expect = 'BLOCK'; tool = 'PowerShell'; inp = @{ command = 'echo x > D:\写真\a.txt' } },
    @{ n = '10 bash rm スラッシュ表記'; expect = 'BLOCK'; tool = 'Bash';       inp = @{ command = 'rm -rf "D:/写真/Z6/test"' } },
    @{ n = '11 Copy-Item 保護先へ';     expect = 'BLOCK'; tool = 'PowerShell'; inp = @{ command = 'Copy-Item .\a.jpg -Destination "D:\写真\Z6\"' } },
    @{ n = '12 Rename-Item';            expect = 'BLOCK'; tool = 'PowerShell'; inp = @{ command = 'Rename-Item "D:\写真\Z6\家" "old"' } },
    @{ n = '13 New-Item';               expect = 'BLOCK'; tool = 'PowerShell'; inp = @{ command = 'New-Item -ItemType Directory "D:\写真\新規"' } },
    @{ n = '14 小文字ドライブ';          expect = 'BLOCK'; tool = 'PowerShell'; inp = @{ command = 'Remove-Item d:\写真\Z50 -Recurse' } },
    @{ n = '15 無関係の削除';            expect = 'ALLOW'; tool = 'PowerShell'; inp = @{ command = 'Remove-Item .\tmp\scratch.txt' } },
    @{ n = '16 2>$null は誤検知しない';  expect = 'ALLOW'; tool = 'PowerShell'; inp = @{ command = 'Get-ChildItem "D:\写真" -Force 2>$null' } },
    @{ n = '17 Read は対象外';          expect = 'ALLOW'; tool = 'Read';       inp = @{ file_path = 'D:\写真\Z6\a.NEF' } }
)

foreach ($c in $cases) {
    $payload = @{
        hook_event_name = 'PreToolUse'
        cwd             = $root
        tool_name       = $c.tool
        tool_input      = $c.inp
    } | ConvertTo-Json -Depth 6 -Compress

    $stdin  = [System.IO.Path]::GetTempFileName()
    $stdout = [System.IO.Path]::GetTempFileName()
    $stderr = [System.IO.Path]::GetTempFileName()
    [System.IO.File]::WriteAllText($stdin, $payload, (New-Object System.Text.UTF8Encoding($false)))

    $proc = Start-Process -FilePath 'powershell' `
        -ArgumentList @('-NoProfile', '-File', "`"$guard`"") `
        -RedirectStandardInput $stdin -RedirectStandardOutput $stdout -RedirectStandardError $stderr `
        -NoNewWindow -Wait -PassThru

    $actual = if ($proc.ExitCode -eq 2) { 'BLOCK' } else { 'ALLOW' }
    if ($actual -eq $c.expect) {
        "OK   {0,-26} {1}" -f $c.n, $c.expect
    } else {
        "FAIL {0,-26} expect={1} actual={2} exit={3}" -f $c.n, $c.expect, $actual, $proc.ExitCode
        $fail++
    }
    Remove-Item $stdin, $stdout, $stderr -Force -ErrorAction SilentlyContinue
}

""
if ($fail -eq 0) {
    "ALL PASS ({0} cases)" -f ($cases.Count + 1)
    exit 0
} else {
    "FAILED: {0} / {1}" -f $fail, ($cases.Count + 1)
    exit 1
}
