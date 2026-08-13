# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 言語設定

- 常に日本語で会話する
- コメントも日本語で記述する
- エラーメッセージの説明も日本語で行う
- ドキュメントも日本語で生成する

## ⚠️ 写真原本の保護（最優先・厳守）

`D:\写真` は約820GB・NEF 18,909枚の**撮り直しのできない原本**である。

- **書き込み・削除・移動・リネームを一切禁止する**
- **読み取りは許可**（ファイル構成の確認、EXIF 参照、仕様調査のサンプル読み出し）
- 書き込みが必要になったら、実行せずにユーザーへ確認する
- 検証は必ずダミーデータ（`tmp/` 配下）に対して行う。
  **本番の写真ディレクトリを出力先にしたテストを書いてはならない**

PreToolUse フック `tools/hooks/photo_guard.ps1` が違反を自動ブロックするが、
これは多層防御の2層目にすぎない。1層目は本ルールの遵守である。
詳細と許可/ブロックの具体例: `doc/agent_execution_rules.md` §1

> フック設定はセッション開始時に読み込まれる。`.claude/settings.json` や
> フック本体を変更した場合、**Claude Code を再起動するまで反映されない**。

## エージェント実行規律

`doc/agent_execution_rules.md` が共通ルールの source of truth。特に頻出するもの:

- **同じエラーで3回失敗したら打ち切る**（§5）。同じ呼び出しをそのまま再送しない
- **日本語を含む `.ps1` は UTF-8 BOM 付きで保存する**（§2）。Windows PowerShell 5.1 は
  BOM なしを CP932 として読むため、パス比較が静かに失敗する。
  **Edit / Write ツールで編集すると BOM が落ちるので毎回付け直すこと**。
  `photo_guard.ps1` を編集したら回帰テストを実行する:
  `powershell -NoProfile -File tools\hooks\test_photo_guard.ps1`
- `.py` / `.md` / `.toml` / `.json` は UTF-8 **BOM なし**・LF
- Python 実行時は `$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"` を付ける（§3）
- `python -c` は3行以下の単純なコードのみ。それ以上は `tmp/` に `.py` を作る（§4）
- `sleep` によるポーリング待機は禁止。長時間コマンドは `run_in_background`
- 一時スクリプト・調査スクリプトは必ず `tmp/` に置く

## 開発ワークフロー

新機能の実装は**計画書ベース**で進める（`doc/agent_execution_rules.md` §8）。

1. `doc/in_progress/_TEMPLATE.md` をコピーして `doc/in_progress/<機能名>_plan.md` を作成
2. **着手前に §4「ユーザー確認事項」を中心にユーザーとレビューし、合意を得る**
3. 作業中はチェックリスト・作業中メモ・課題を随時更新（引き継ぎ書として書く）
4. 完了後 `doc/completed/` へ移動

TDD（red-green-refactor）を基本とする。テストを1つ書いて落とし、通す最小の実装をして、
リファクタする。「全部テストを書いてから全部実装」ではない。

**設計判断は `doc/architecture.md` に反映する。** 特に「やらないと決めたこと」は
§7 の表に追記し、別セッションでの再提案を防ぐ。

Git はユーザーがコミットする。エージェントは `git add <明示パス>` まで。
`git add -A` / `git add .` は禁止。worktree とサブエージェント委譲は使わない。

## Project overview

カメラの RAW 現像ワークフローを支える自作ツール群。Lightroom のコスト削減のため、
**現像本体は darktable（既製品）に任せ、その前後の欠けている工程を自作する**。

```
SDカード → [Importer] → D:\写真\<機種>\<YYYYMMDD 撮影名>\
                              ↓
                        [darktable]  ← 既製品。Photolab は内部状態に触らない
                              ↓
                     <撮影フォルダ>\darktable\*.jpg
                              ↓
                        [Exporter] → NAS (Synology) / OneDrive の <撮影フォルダ名>\
```

**着手前に `doc/architecture.md` を読むこと。** 設計上の source of truth であり、
実装より優先される。特に以下は複数ファイルを読んでも分からない前提知識:

- **darktable は交換可能な部品として扱う**（§3.1）。`library.db` は読みも書きもしない。
  現像パラメータの持ち主は darktable ひとつに限る
- **カタログは資産管理台帳ではない**（§3.3）。答えるのは「このカットは取り込み済みか？」
  の1問だけ。レーティングや現像状態は持たない
- **重複判定キーは Nikon MakerNote のシリアル番号 + ショットカウント**（§5.3）。
  リネームやコピーで壊れない。これがプロジェクトの技術的な肝
- **原画は機種別階層、配布先はフラットでマージ**（§4）。`Z6\` `Z50\` は所有者の区別も兼ねる
- **やらないと決めたこと一覧**（§7）

## 現在の状態

**2026-08-12 時点: Phase 1（Importer）+ Phase 1.5（常駐）完了、配布可能。**
実機カード（Nikon Z6 / 355 カット）で受け入れテストを通過し、
インストーラーからの導入も確認済み。テスト 219 件。

```
photolab/
  cli.py  __main__.py
  core/   models.py naming.py metadata.py dedup.py catalog.py scanner.py
          copier.py importer.py thumbnail.py config.py developer.py
          maintenance.py watcher.py single_instance.py
  ui/     app.py main_window.py shot_model.py shot_delegate.py dest_bar.py
          tray.py workers.py theme.py assets/（アプリアイコン）
tools/    build.ps1         配置版のビルド（PyInstaller / GPL 混入検査つき）
          make_installer.ps1 インストーラー生成（Inno Setup）
          make_shortcut.ps1  起動ショートカット生成
          make_icon.py       アイコン生成（生成物はコミット済み）
          install_rapidraw.ps1 RapidRAW を公式から取得（同梱しない）
          hooks/             写真原本保護フック
installer/ photolab.iss  README.md（**利用者向け**。配布物に同梱）
tests/    core/ とソースを 1:1 ミラー（156 テスト）
data/test/  実データのフィクスチャ（git 管理外）
```

**GUI を触るときは `.claude/skills/photolab-gui/SKILL.md` を必ず読むこと。**
ワーカーの GC、状態の描き分け、文字色のハードコード禁止など、実際に踏んだ罠を記録している。

## Commands

```powershell
# テスト（data/test/ が無い環境では実データ系が skip される）
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"; .\venv\Scripts\python.exe -m pytest tests -q

# GUI / 常駐
.\venv\Scripts\python.exe -m photolab gui
.\venv\Scripts\python.exe -m photolab watch    # タスクトレイに常駐

# CLI
.\venv\Scripts\python.exe -m photolab list
.\venv\Scripts\python.exe -m photolab import --source L:\ --dest "tmp\out\20260811 テスト" [--dry-run]
    [--split-by-date] [--open-darktable] [--develop-jpeg] [--catalog PATH]

# カタログの点検（実ファイルが無い記録の検出。--fix で記録だけ削除）
.\venv\Scripts\python.exe -m photolab doctor [--fix] [--verify-hash]

# 起動用ショートカットを作る（pythonw なのでコンソール窓が出ない）
powershell -NoProfile -ExecutionPolicy Bypass -File tools\make_shortcut.ps1 [-Desktop] [-StartMenu] [-Startup]

# 配布物を作る（ビルドとインストーラーは別スクリプト）
powershell -NoProfile -ExecutionPolicy Bypass -File tools\build.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File tools\make_installer.ps1
```

**README は2つある。** `README.md` は開発者向け、`installer/README.md` は
**利用者向け**（配布物に同梱される）。利用者向けの説明を前者に書かない。

> `pythonw` から起動すると **stderr がどこにも出ない**。起動時に落ちた場合は
> `%LOCALAPPDATA%\Photolab\error.log` に traceback が残り、ダイアログも出る。

**Python 実行は必ず `.\venv\Scripts\python.exe`**（素の `python` は venv 外を拾う）。
**動作確認の出力先は必ず `tmp/` 配下**にする（`D:\写真` を出力先にしない）。

技術スタックは `doc/architecture.md` §8。EXIF / MakerNote は **GPL 回避のため自前実装**
（`core/metadata.py`）であり、`pyexiv2` は開発時の答え合わせ専用（`requirements-dev.txt`）。

## Coding conventions

- **import 形式は1つに統一する**: `from photolab.core import ...`。
  stocktool では複数の import 形式が混在して常時の混乱要因になったため、
  本プロジェクトでは最初から1形式に固定する
- **テストは `tests/` にソースと 1:1 ミラー**し `test_` を前置する
  （`photolab/core/naming.py` → `tests/core/test_naming.py`）
- GUI 非依存のロジックは `photolab/core/` に置き、PySide6 を import しない。
  テスト可能性のため、UI 層とドメインロジックを混ぜない
