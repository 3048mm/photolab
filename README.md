# Photolab

カメラの RAW 現像ワークフローを支える自作ツール群。

Lightroom のコスト削減のため、**現像本体は darktable / RapidRAW（既製品）に任せ、
その前後の欠けている工程を自作する**方針です。

```
SDカード → [Importer] → D:\写真\<機種>\<YYYYMMDD 撮影名>\
                              ↓
                     [darktable / RapidRAW]  ← 既製品。内部状態には触らない
                              ↓
                    <撮影フォルダ>\darktable\*.jpg
                              ↓
                        [Exporter] → NAS / OneDrive
```

**利用者向けの説明は [installer/README.md](installer/README.md)** にあります
（配布物に同梱されるもの）。この README は開発者向けです。

## 状態

| Phase | 内容 | 状態 |
| :--- | :--- | :--- |
| 1 | Importer（取り込み・重複判定・コピー検証・GUI） | 完了 |
| 1.5 | 常駐プロセスによる自動検出 | 実装済み |
| 2 | Exporter（NAS / OneDrive への配布） | 未着手 |
| 3 | XMP 連携（レーティング） | 構想 |

## 着手する前に

**[doc/architecture.md](doc/architecture.md) を読んでください。**
設計上の source of truth であり、実装より優先されます。特に以下は
コードを読んでも分からない前提知識です。

- **現像ソフトは交換可能な部品として扱う**（§3.1）。`library.db` は読みも書きもしない
- **カタログは資産管理台帳ではない**（§3.3）。答えるのは「取り込み済みか？」の1問だけ
- **重複判定キーは Nikon MakerNote のシリアル番号 + ショットカウント**（§5.3）。
  リネームやコピーで壊れない。このプロジェクトの技術的な肝
- **やらないと決めたこと一覧**（§7）

`D:\写真` は約820GB・NEF 18,909枚の**撮り直しのできない原本**です。
書き込み・削除・移動を禁止しており、`tools/hooks/photo_guard.ps1` が機械的に
ブロックします。詳細は [doc/agent_execution_rules.md](doc/agent_execution_rules.md) §1。

## 開発環境

```powershell
py -3.12 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

**Python 実行は必ず `.\venv\Scripts\python.exe`**（素の `python` は venv 外を拾います）。

### テスト

```powershell
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"
.\venv\Scripts\python.exe -m pytest tests -q
```

`data/test/` に実データのフィクスチャを置くと、実データ系のテストも走ります
（git 管理外。無い環境では skip されます）。

写真原本保護フックの回帰テスト:

```powershell
powershell -NoProfile -File tools\hooks\test_photo_guard.ps1
```

### 実行

```powershell
.\venv\Scripts\python.exe -m photolab gui        # GUI
.\venv\Scripts\python.exe -m photolab watch      # タスクトレイに常駐
.\venv\Scripts\python.exe -m photolab list       # 媒体の一覧
.\venv\Scripts\python.exe -m photolab import --source L:\ --dest "tmp\out\テスト" --dry-run
.\venv\Scripts\python.exe -m photolab doctor     # カタログの点検
```

**動作確認の出力先は必ず `tmp/` 配下**にしてください（`D:\写真` を出力先にしない）。

コンソール窓なしで起動するショートカットを作る:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\make_shortcut.ps1 [-Desktop] [-StartMenu] [-Startup]
```

## ビルドとインストーラー

ビルドとインストーラー作成は**別のスクリプト**です。配置版だけ欲しい場合に
Inno Setup を要求しないためです。

### 1. 配置版をビルドする

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\build.ps1
```

- テスト → PyInstaller（onedir）→ `dist\Photolab\`
- **GPL 依存（pyexiv2 / exiv2）が混入していないか検査**し、あれば失敗します
- `-SkipTests` でテストを飛ばせます（普段は付けない）
- `-DistPath` で出力先を変えられます

出力は約 160MB、実行ファイルは2つです。

| ファイル | 用途 |
| :--- | :--- |
| `Photolab.exe` | コンソール無し。引数なしで GUI、`watch` で常駐 |
| `photolab-cli.exe` | コンソールあり。`doctor` や `import` 用 |

### 2. インストーラーを作る

```powershell
winget install JRSoftware.InnoSetup   # 初回だけ
powershell -NoProfile -ExecutionPolicy Bypass -File tools\make_installer.ps1
```

`dist\Photolab-<版>-setup.exe` ができます（約 44MB）。
版は `photolab/__init__.py` の `__version__` を正とし、`-Version` で上書きできます。

インストーラーの仕様は [installer/photolab.iss](installer/photolab.iss)。

- **管理者権限を要求しない**（ユーザー単位でインストール）
- 選択項目: デスクトップのショートカット / ログイン時の常駐 / RapidRAW の取得
- **アンインストールでもカタログと設定は消しません**（写真と対で意味を持つため）

### アイコンを作り直す

```powershell
.\venv\Scripts\python.exe tools\make_icon.py
```

生成物はコミット済みなので、普段は実行不要です。

## 構成

```
photolab/
  cli.py  __main__.py
  core/   models.py naming.py metadata.py dedup.py catalog.py scanner.py
          copier.py importer.py thumbnail.py config.py developer.py
          maintenance.py watcher.py single_instance.py
  ui/     app.py main_window.py shot_model.py shot_delegate.py dest_bar.py
          tray.py workers.py theme.py assets/
tests/    core/ とソースを 1:1 ミラー
tools/    build.ps1 make_installer.ps1 make_shortcut.ps1 make_icon.py
          install_rapidraw.ps1 hooks/
installer/ photolab.iss  README.md（利用者向け）
doc/      architecture.md  agent_execution_rules.md  completed/  in_progress/
```

**GUI を触るときは `.claude/skills/photolab-gui/SKILL.md` を必ず読んでください。**
ワーカーの GC、タイマーのスレッド、状態の描き分けなど、実際に踏んだ罠が書いてあります。

`core/` は GUI 非依存です。**PySide6 を import しないでください。**

## ライセンス方針

本体は [MIT](LICENSE)。**製品コードに GPL の依存を持ちません。**

EXIF / Nikon MakerNote / QuickTime の解析は標準ライブラリだけで自前実装しています
（`core/metadata.py`）。`pyexiv2` は GPL-3.0 なので**開発時の答え合わせ専用**とし、
`requirements-dev.txt` に隔離しています。ビルドスクリプトが混入を検査します。

依存とライセンスの一覧は [NOTICE.md](NOTICE.md)。

## 進め方

新機能は**計画書ベース**で進めます（[doc/agent_execution_rules.md](doc/agent_execution_rules.md) §8）。

1. `doc/in_progress/_TEMPLATE.md` をコピーして計画書を作る
2. **着手前に「ユーザー確認事項」をレビューして合意する**
3. 作業中はチェックリストと課題を随時更新する
4. 完了後 `doc/completed/` へ移す

TDD（red-green-refactor）を基本とします。設計判断は `doc/architecture.md` に反映し、
特に「やらないと決めたこと」は §7 に追記して再提案を防ぎます。
