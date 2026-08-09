# エージェント一般動作ルール (General Agent Execution Rules)

AI エージェントがコマンド実行・ファイル操作を行う際の共通ルール。
エージェントはこれを遵守し、無駄なリトライと事故を回避すること。

stocktool プロジェクトの同名ドキュメントをベースに、Photolab 固有の
**写真原本保護**（§1）を最上位ルールとして追加している。

---

## 1. 写真原本の保護（最重要 / 厳守）

### 問題

`D:\写真` は約820GB・NEF 18,909枚の**撮り直しのできない原本**である。
バックアップではない。エージェントの誤操作による削除・上書き・リネームは
回復不可能な損失になる。

### 対策ルール

- **`D:\写真` 配下への書き込み・削除・移動・リネームを一切禁止する。**
- **読み取りは許可する** — ファイル構成の確認、EXIF/メタデータの参照、
  仕様調査のためのサンプル読み出しは自由に行ってよい。
- 書き込みを伴う操作が必要になったら、**実行せずにユーザーへ確認する**。
- Importer / Exporter の検証は**必ずダミーデータ**に対して行う。
  ダミーの媒体・出力先は `tmp/` 配下に作る。
  **本番の写真ディレクトリを出力先に指定したテストを書いてはならない。**

### 機械的な強制

PreToolUse フック `tools/hooks/photo_guard.ps1` が違反を自動ブロックする
（`.claude/settings.json` に登録済み）。

| ツール | ブロック条件 |
| :--- | :--- |
| Write / Edit / MultiEdit / NotebookEdit | `file_path` が保護ルート配下 |
| Bash / PowerShell | 破壊的コマンドの対象・リダイレクト出力先・パイプ先が保護ルート |

許可される例:

```powershell
Get-ChildItem "D:\写真\Z6" -Force              # OK: 一覧
Get-ChildItem "D:\写真" | Out-File list.txt     # OK: 出力先は外部
```

ブロックされる例:

```powershell
Remove-Item "D:\写真\Z6\test" -Recurse          # NG
Get-ChildItem "D:\写真" -Recurse | Remove-Item  # NG
Copy-Item .\a.jpg -Destination "D:\写真\Z6\"    # NG
echo x > D:\写真\a.txt                          # NG
```

> [!IMPORTANT]
> フックはあくまで**多層防御の2層目**であり、シェルスクリプト経由の間接的な
> 操作まで捕捉できるわけではない。1層目は本ルールの遵守である。
>
> また Claude Code はフック設定を**セッション開始時に読み込む**。
> `.claude/settings.json` や本フックを変更した場合は
> **Claude Code の再起動が必要**で、それまでフックは有効にならない。

保護範囲を広げる場合は `photo_guard.ps1` 冒頭の `$ProtectedRoots` に追記する。

---

## 2. PowerShell スクリプトの文字コード（Photolab 固有）

### 問題

Windows PowerShell 5.1 は **BOM なしの `.ps1` を CP932 として読む**。
日本語（`写真` など）を含むスクリプトを BOM なし UTF-8 で保存すると、
文字列リテラルが壊れて**パス比較が静かに失敗する**。フックの場合、
エラーにならずガードが無効化されるため危険。

### 対策ルール

- 日本語を含む `.ps1` は **UTF-8 BOM 付き**で保存する。
- **Edit / Write ツールで編集すると BOM が落ちる。** 編集のたびに付け直すこと。

```powershell
$p = "tools\hooks\photo_guard.ps1"
$t = [System.IO.File]::ReadAllText($p, (New-Object System.Text.UTF8Encoding($false)))
[System.IO.File]::WriteAllText($p, $t, (New-Object System.Text.UTF8Encoding($true)))
```

- `.py` / `.md` / `.toml` / `.json` は **UTF-8 BOM なし・LF** とする（BOM を付けない）。

`photo_guard.ps1` を編集したら**必ず回帰テストを実行する**（BOM の有無もチェックする）。

```powershell
powershell -NoProfile -File tools\hooks\test_photo_guard.ps1
```

---

## 3. Windows 文字コード問題 (CP932 / UTF-8 衝突)

### 問題

| 症状 | 原因 |
| :--- | :--- |
| `UnicodeDecodeError` / `UnicodeEncodeError` | Python の stdout が CP932 で、日本語出力が失敗 |
| エージェント実行の強制終了 | コマンド出力に CP932 で解釈不能なバイト列が含まれる |
| ファイル書き込み時の BOM 混入 | PowerShell の `Set-Content` / `Out-File` の既定挙動 |

### 対策ルール

- **Python 実行時**: 必ず先頭に付与する。

  ```powershell
  $env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"; python script.py
  ```

- **ファイル書き込み**: PowerShell の `>` リダイレクトや `Set-Content` を使わない。
  Write ツール、または .NET の `UTF8Encoding` で明示的にエンコーディングを指定する。

---

## 4. PowerShell での Python ワンライナー (`python -c`) の制限

### 問題

| 症状 | 原因 |
| :--- | :--- |
| `SyntaxError: unterminated string literal` | f-string 内のクォートが PowerShell のクォート処理と衝突 |
| `SyntaxError: invalid syntax` (try/except) | `-c` モードではセミコロン区切りで記述不可 |
| 意図しないエスケープ | PowerShell が `\"` を二重展開する |

### 対策ルール

- **3行以下の単純なコード**: `python -c` を使ってよい。f-string 内にクォートを含めない。
- **4行以上、または try/except / for / if を含むコード**: 必ず `.py` ファイルを作成してから実行する。
- **一時スクリプトの配置場所**: `tmp/` 配下（例: `tmp/probe_exif.py`）。

---

## 5. 同じエラーでのリトライ上限

- **同じエラーで3回リトライしたら打ち切り**、内容をユーザーに報告して判断を仰ぐ。
- リトライ時は**必ず前回と異なるアプローチ**を試す
  （`-c` → スクリプトファイル化、ライブラリ変更、直接実行 → pytest 経由 等）。
- `File has not been read yet` / `File has been modified since read` で Edit が
  拒否されたら、**対象ファイルを Read し直してから** Edit する。
  コンテキスト要約後は Read 状態が失われている。
- `sleep` によるポーリング待機を禁止する（この環境ではブロックされる）。
  長時間コマンドは `run_in_background` で実行し、完了通知を待つ。

---

## 6. 依存パッケージ

- 新しいライブラリを使う前に `pip show <package>` で**インストール済みかを確認**する。
- Python 実行は常に**プロジェクトの venv** を使う（`.\venv\Scripts\python.exe`）。
  素の `python` は venv 外の Python を拾い `ModuleNotFoundError` の原因になる。

---

## 7. Git 操作時の合意形成ルール

> [!NOTE]
> 本プロジェクトは 2026-08-07 時点で git 未初期化。初期化後に本節が適用される。

- **コミットはユーザーが行う。** エージェントは `git add <明示パス>` までとする。
- `git add -A` / `git add .` は**禁止**（写真ファイルやキャッシュの誤コミット防止）。
- main への直接 push、`--amend`、force-push は禁止。push・PR 作成は都度ユーザー指示。
- **worktree とサブエージェント委譲は使わない**（プロジェクト規模に対して過剰）。

---

## 8. 新機能の実装フロー

1. `doc/in_progress/_TEMPLATE.md` をコピーして `doc/in_progress/<機能名>_plan.md` を作成し記入する
2. 着手前に **§4「ユーザー確認事項」を中心にユーザーとレビューし、合意する**
3. 作業中は進捗チェックリスト・作業中メモ・発生した課題を随時更新する
   （別セッションへの引き継ぎ・中断からの復元に使われる前提で書く）
4. 全タスク（ドキュメント更新を含む）完了後、検証結果を記入して `doc/completed/` へ移動する

設計判断は `doc/architecture.md` に反映する。特に「やらないと決めたこと」は
§7 の表に追記し、再提案を防ぐ。

---

## 9. 自己更新ルール

- 本ドキュメントに記載のない**新しい一般的な問題パターン**を発見したら追記すること。
- 追記時は「症状」「原因」「対策ルール」の3点セットを必ず含める。
- 更新履歴に日付と変更内容を記録する。

---

## 更新履歴

- 2026-08-07: 初版作成。stocktool の同名ドキュメントをベースに、
  §1 写真原本の保護と §2 PowerShell スクリプトの文字コードを新設。
  worktree / サブエージェント委譲の項目は削除。
