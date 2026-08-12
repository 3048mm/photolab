# Photolab

SD カードから写真を取り込むツール。Nikon の RAW ワークフローを想定しています。

カードを挿すと自動で立ち上がり、サムネイルを見ながら取り込む写真を選び、
`YYYYMMDD-hhmmss_NN` の規則でリネームしてコピーします。
取り込んだあとは現像ソフト（RapidRAW / darktable）を開くところまで面倒を見ます。

**同じ写真を二度取り込みません。** カメラのシリアル番号とショットカウントで
判定するので、カードを消さずに使い回しても、別のカードに同じカットが入っていても、
取り込み済みのものはグレーアウトされます。

## できること

- **カードの自動検出** — タスクトレイに常駐し、`DCIM` を持つカードを挿すと開く
- **サムネイル選択** — RAW+JPEG のペアは1カットとして扱う。動画も一覧に出る
- **重複判定** — シリアル番号 + ショットカウント。リネームやコピーで壊れない
- **コピー検証** — xxHash3 で照合し、転送中の破損を検出する
- **日付ごとの振り分け**（任意）— 1枚のカードに複数日が混在していても分けられる
- **現像ソフトの起動** — RapidRAW または darktable を取り込み後に開く

## インストール

[Releases](https://github.com/3048mm/photolab/releases) から
`Photolab-<版>-setup.exe` を取得して実行してください。

管理者権限は要りません。ユーザー単位でインストールされます。

> **SmartScreen の警告について**
>
> コード署名証明書を使っていないため、初回起動時に
> 「WindowsによってPCが保護されました」と表示されます。
> 「詳細情報」→「実行」で進めてください。
> 気になる場合は下記の手順でソースからビルドできます。

インストーラーでは次を選べます。

| 選択肢 | 内容 |
| :--- | :--- |
| デスクトップにショートカット | |
| ログイン時に常駐 | カードを挿すと取り込み画面が開く |
| RapidRAW をダウンロードして入れる | 公式リリースから取得（同梱していません） |

## 使い方

1. **出力先の親フォルダを登録する** — 初回だけ `＋` を押して選びます（例 `D:\写真\Z6`）。
   以降はボタン1つで切り替わります
2. **カードを挿す** — 常駐していれば自動で開きます
3. **取り込むカットを選ぶ** — 既定は未取り込みのみ。Shift+クリックで範囲選択
4. **フォルダ名を決める** — 撮影日が入った名前を提案します。既存フォルダも選べます
5. **［取り込み開始］**

取り込み中は［中断］で止められます。**途中まで取り込んだファイルは残ります**
（消えると困るため）。中断したカットは「未取り込み」のままです。

### サムネイルの見方

| 表示 | 意味 |
| :--- | :--- |
| チェック | 取り込む対象。クリックしただけでは変わりません |
| 青い枠 | 選択中（操作の対象） |
| グレースケール + ✓ バッジ | 取り込み済み |
| `RAW+JPG` / `RAW` / `JPG` | カットの構成 |
| `▶ 0:14` | 動画と再生時間 |
| 黄色い △ | EXIF が取れず、判定が弱いカット |

## コマンドライン

`photolab-cli.exe` を使います（インストール先に同梱）。

```
photolab-cli list                      取り込めるカードを一覧する
photolab-cli import --source L:\ --dest "D:\写真\Z6\20260812 花火" [--dry-run]
photolab-cli doctor [--fix]            カタログと実ファイルの食い違いを調べる
```

`doctor` は、取り込んだ後にファイルを消したときに使います。
**カタログの記録だけを消し、写真には触れません。**

## データの置き場所

```
%LOCALAPPDATA%\Photolab\catalog.db     取り込み済みの記録
%LOCALAPPDATA%\Photolab\config.toml    設定
%LOCALAPPDATA%\Photolab\thumbnails\    サムネイルのキャッシュ
%LOCALAPPDATA%\Photolab\error.log      起動に失敗したときの記録
```

**アンインストールしてもカタログと設定は消しません。** 取り込み済みの記録は
写真と対で意味を持つため、消すと「取り込んだかどうか」が分からなくなります。
不要なら上のフォルダを手で削除してください。

## ソースからビルドする

```powershell
py -3.12 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements-dev.txt

# テスト
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"
.\venv\Scripts\python.exe -m pytest tests -q

# 実行
.\venv\Scripts\python.exe -m photolab gui

# インストーラーを作る（Inno Setup が必要: winget install JRSoftware.InnoSetup）
powershell -NoProfile -ExecutionPolicy Bypass -File tools\build.ps1
```

## ライセンス

Photolab 本体は [MIT](LICENSE)。

**製品コードに GPL の依存を持たない方針**です。EXIF / Nikon MakerNote の解析は
標準ライブラリだけで自前実装しています。依存とライセンスの一覧は [NOTICE.md](NOTICE.md)。

現像ソフト（RapidRAW: AGPL-3.0 / darktable: GPL-3.0）は**同梱していません**。
コマンドラインで起動するだけなので、Photolab のライセンスには影響しません。

## 設計について

設計の意図と「やらないと決めたこと」は [doc/architecture.md](doc/architecture.md)
に書いてあります。実装より優先される文書です。
