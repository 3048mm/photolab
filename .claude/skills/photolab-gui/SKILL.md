---
name: photolab-gui
description: Photolab の PySide6 GUI を実装・変更するときの規約。core/ui の分離、サムネイルグリッド（QListView IconMode）、ワーカースレッド、日本語フォント、High DPI の扱いを定める。ui/ 配下のファイルを触るとき、GUI の画面・ウィジェット・スレッド処理を追加/修正するときに読む。
---

# Photolab GUI 実装規約

PySide6 (Qt) 6.11 / Windows 11 が主戦場。将来の Linux 移管を考慮する。

## 1. 最優先: core を汚さない

- **`photolab/core/` から PySide6 を import してはならない。** テスト可能性のため
- **GUI 側にドメインロジックを書かない。** 判断が要るものは core に関数を足して呼ぶ
- 迷ったら「この処理は CLI からも使うか？」で判断する。使うなら core

```python
# NG: UI がファイル名を組み立てている
name = f"{dt:%Y%m%d-%H%M%S}_{n:02d}{ext}"

# OK: core に委ねる
from photolab.core.naming import assign_basenames
```

`plan()` / `execute()`（`core/importer.py`）が GUI と CLI の共通の入り口。
GUI は `plan()` の結果を表示し、選択を `execute()` に渡すだけにする。

**`execute()` に渡す計画と選択は必ず同じ計画から取り出す。** `PlannedShot` は
コピー先のパスを内部に持つため、計画を作り直したのに選択が古いままだと
**古いコピー先へ書き込まれる**（2026-08-11 に実際に踏んだ）。

出力先が変わったら `importer.build_plan()` で作り直す。
走査（`scan_card`）を伴わないためカードを読み直さず軽い。

## 2. GUI スレッドを止めない

**カード読み出し・コピー・サムネイル生成は絶対に GUI スレッドで実行しない。**
355 カットのカードで数十秒かかる。

QThread はサブクラス化せず、**ワーカーオブジェクトを moveToThread する**形にする。

```python
class ScanWorker(QObject):
    progress = Signal(int, int)          # 現在, 全体
    finished = Signal(object)            # 結果
    failed = Signal(str)

    def __init__(self, card_root, dest_root, catalog_path):
        super().__init__()
        # Path や str だけを持つ。Catalog 接続は run() の中で開く
        self._card_root = card_root

    @Slot()
    def run(self):
        try:
            ...
        except Exception as e:
            self.failed.emit(str(e))
```

- **sqlite の接続をスレッド間で共有しない。** `Catalog` はワーカーの中で開いて閉じる
- ワーカーに渡すのは `Path` / `str` / dataclass などの不変値だけにする
- 例外は握って `failed` シグナルで返す。ワーカー内での未捕捉例外はアプリを落とす

### ⚠ ワーカーへの参照を必ず保持する

`moveToThread()` は **Qt に所有権を渡さない**。ワーカーをローカル変数のままにすると
関数を抜けた時点で Python 側がガベージコレクトし、
**スレッドは起動するが何も実行されないまま終わる**（例外も出ないので気づきにくい）。

```python
# NG: worker が GC され、finished シグナルが永久に来ない
def start(self):
    worker = PlanWorker(...)
    thread = QThread(self)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    thread.start()

# OK: スレッドとワーカーを組で保持し、終了時に外す
    self._jobs.append((thread, worker))
    thread.finished.connect(lambda: self._drop_job(thread))
```

このプロジェクトでは実際にこれで詰まった（2026-08-10）。
ワーカー単体のスクリプトではモジュール変数として生き残るため**再現しない**。
「単体では動くのに GUI から呼ぶと固まる」ときは、まずここを疑う。

## 3. サムネイルグリッド

`QListView` の `IconMode` + `QAbstractListModel`。`QListWidget` は使わない
（355 件のアイテムを都度生成するとメモリと生成コストが無駄）。

```python
view.setViewMode(QListView.ViewMode.IconMode)
view.setResizeMode(QListView.ResizeMode.Adjust)   # 幅に応じて折り返す
view.setUniformItemSizes(True)                    # 全アイテム同サイズ=描画が速い
view.setSelectionMode(QListView.SelectionMode.ExtendedSelection)
view.setIconSize(QSize(192, 128))
```

### サムネイルの供給

**`ThumbnailCache.generate_many()` を使う。読み出しは直列に保つこと。**
実測でカードの並列読み出しは逆効果だった（`doc/architecture.md` §5.4）。

- モデルの `data()` は**キャッシュ済みなら返し、無ければ None を返して即座に戻る**。
  `data()` の中でサムネイルを生成してはならない（スクロールが固まる）
- 生成はワーカーが進め、1件できるたびに `dataChanged` を出してその行だけ再描画する
- 未生成のセルはプレースホルダ（グレーの矩形）にする

### 選択とチェックを分ける

**チェックボックス = 取り込む/取り込まない（永続的な状態）**、
**Qt の選択 = 操作対象（一時的）**。混同しない。

```python
view.setSelectionMode(QListView.SelectionMode.ExtendedSelection)  # Shift/Ctrl が効く
```

モデルは `Qt.ItemDataRole.CheckStateRole` を実装し、`flags()` に
`Qt.ItemFlag.ItemIsUserCheckable` を立てる。

- **1枚クリックしただけでチェックが消えてはならない。** 拡大確認のたびに
  それまでの取り込み対象が壊れると使い物にならない
- チェックボックスのクリックは、**複数選択中なら選択中すべてに適用**する
- Space キーで選択中すべてのチェックを反転
- 「取り込む N カット」のカウントは**チェック数**（選択数ではない）

範囲選択（Shift+クリック）は `ExtendedSelection` の標準動作でそのまま効く。
自前で実装しないこと。

### 状態の見せ方: 別々の視覚チャンネルに割り当てる

複数の状態が**同時に成立しうる**（取り込み済みでチェック済みで選択中、など）。
同じチャンネルに重ねると見分けがつかなくなるため、次のように分ける。

| 状態 | チャンネル | 見せ方 |
| :--- | :--- | :--- |
| 選択中（操作対象） | **外枠** | アクセント色の 3px の枠 + 薄い背景 |
| チェック（取り込む） | **明るさ** | 未チェックはサムネイルを暗くする + 左上のチェックボックス |
| 取り込み済み | **彩度** | グレースケール + 左下に「済」バッジ |
| 動画 | 右下バッジ | `▶ 0:49`（再生時間つき） |
| EXIF が取れない | 右上バッジ | **黄色い △**。ツールチップで理由を出す |
| サムネイル生成失敗 | 代替アイコン | **空セルにしない**（数が合わなくなる） |

**`ForegroundRole` によるグレーアウトは効かない。** IconMode ではラベル文字の色しか
変わらず、セルの視覚的な重みを占めるサムネイル画像はそのままになる。
`QStyledItemDelegate` を自前で用意して描く（`ui/shot_delegate.py`）。

グレースケール変換は**サムネイル受け取り時に1度だけ**行い、モデルに持たせる。
`paint()` の中で変換すると数百セルのスクロールが重くなる。

自前デリゲートにすると既定のチェック操作が効かなくなるので、
`editorEvent()` でチェックボックス領域のクリックを拾うこと。

### 配色は `ui/theme.py` に集約する

色・余白・フォント・アイコンは `photolab/ui/theme.py` から取る。各所に散らさない。
`theme.apply(app)` がスタイル・パレット・フォント・アイコンをまとめて設定する。

- **本アプリはダーク配色**。写真の周囲を暗くして画像の色を正しく見せるため
- **ダーク配色には Fusion スタイルが要る。** Windows 標準スタイルはパレットの多くを
  無視して OS のテーマ色で描いてしまう
- **タイトルバーは `styleHints().setColorScheme(Qt.ColorScheme.Dark)`** で暗くする。
  パレットはクライアント領域にしか効かず、枠だけ明るいままになる
- サムネイルの上に置くバッジは、**暗い写真にも明るい写真にも乗る**ことを確認する。
  「取り込み済み」バッジは暗い下地だと黒い写真に溶けたため、明るい下地 + 暗い印にした
- **ビューの下地は `viewport()` に設定する。** ビュー本体のパレットに入れても描画されない
- **「弱める」表現に不透明度を使わない。** 下地が明るいと不透明度を下げた分だけ
  白く飛び、「暗くして目立たなくする」意図と逆になる。暗い色を重ねる（`UNCHECKED_VEIL`）

### 終了時に削除済みの QThread へ触らない

`thread.finished` で `deleteLater` した後も Python 側の参照は残る。
`closeEvent` でまとめて `quit()` すると C++ 側が消えていて `RuntimeError` になる。
`try/except RuntimeError` で握ること。

- **アクセント色は操作に関わるものだけに使う**（チェック、選択、既定ボタン）。
  「取り込み済み」のような**状態の説明**には中間色を使う。
  情報バッジにアクセント色を使うと、押せるものに見えてしまう
- **文字（▶ や ✓）を字形に頼らない。** フォントに無いと豆腐になる。
  再生マークもチェックマークも多角形・線で描く
- **OS 標準のチェックボックスを写真の上に置かない。** 未チェック状態が
  白地に薄い枠で描かれ、明るい写真の上では消える。自前で描いて影を付ける

### オフスクリーン描画では文字が豆腐になる

`QT_QPA_PLATFORM=offscreen` で `grab()` すると**全ての文字が □ になる**。
実装の不具合ではなく offscreen QPA の制約。

タイポグラフィを確認したいときは**プラットフォームを指定せず**、
`show()` を呼ばずに `widget.grab()` する（ウィンドウは画面に出ない）。

### 文字色をハードコードしない

**背景の上に直接置く文字は `option.palette` から色を取る。**
ハードコードするとテーマの片方で読めなくなる。

```python
# NG: ダークテーマ前提。ライトテーマの白背景では薄すぎて読めない
painter.setPen(QColor("#c8c8c8"))

# OK: パレットから。無効状態は Disabled グループを使う
group = QPalette.ColorGroup.Normal if checked else QPalette.ColorGroup.Disabled
painter.setPen(option.palette.color(group, QPalette.ColorRole.Text))
```

サムネイル画像の**上に重ねるバッジ**は例外で、暗い下地 + 白文字に固定してよい
（下地の色を自分で描いているため、テーマに依存しない）。

フォントサイズも勝手に縮めない。既定の `option.font` を使う。

既定の選択は「未取り込みのみ」（`ImportPlan.new_shots`）。Q3 の合意。

## 4. 日本語フォント

Windows の既定フォントは日本語に対して不格好になることがある。
**明示的に指定し、フォールバックを持たせる。**

```python
font = QFont()
font.setFamilies(["Yu Gothic UI", "Meiryo UI", "Noto Sans CJK JP", "sans-serif"])
app.setFont(font)
```

- Linux 移管を考えて `Noto Sans CJK JP` をリストに残す
- ハードコードした固定ピクセル幅でラベルを作らない（フォントで幅が変わる）。
  レイアウトに任せる

## 5. High DPI と表示

- Qt 6 は High DPI スケーリングが既定で有効。**手動で有効化する古いコードを書かない**
- アイコン・プレースホルダは `devicePixelRatio` を考慮する。
  サムネイルは長辺 512px でキャッシュしてあるので、192px 表示なら 2倍 DPI でも足りる
- ウィンドウサイズと位置は `config.toml` に保存する（Step 11）

## 6. パスの表示

- ユーザーに見せるパスは `str(path)` そのまま（Windows の `\` のまま）でよい
- **長いパスはラベルで省略する**（`QFontMetrics.elidedText`）。
  ウィンドウ幅を押し広げさせない

## 7. 破壊的操作の確認

写真原本を扱うツールである。

- 出力先が**既存の非空フォルダ**のときは、マージになる旨を明示して確認する
- 取り込み中の中断は「コピー済みのファイルは残る」と明示する（ロールバックしない設計）
- **削除機能を GUI に作らない。** カード上のファイル削除も出力先の削除も持たない

## 8. テスト

GUI 自体の自動テストは Phase 1 では書かない（`pytest-qt` を導入しない）。
代わりに**ロジックを core に置いてテストする**。

GUI 層に置いてよいのは「表示」と「入力の受け取り」だけ。
そこにテストしたくなるロジックが生えたら、それは core に移すサイン。

動作確認は CLI と同じ経路で行う:

```powershell
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"
.\venv\Scripts\python.exe -m photolab import --source "tmp\mini_card" --dest "tmp\dummy_dest\test" --catalog "tmp\test_catalog.db" --dry-run
```

## 9. 出力先の提案

媒体のボリュームラベルに機種名が入っている（実機カードは `NIKON Z 6`）。
`MediaCandidate.label` から `D:\写真\Z6\` を提案できる。

ただし**固定テンプレートで出力先を組み立てない**（`doc/architecture.md` §4.1）。
`家\` のような中間階層や旅行の日別サブ階層が実在するため、
**親フォルダを選ばせ、その下のフォルダ名を提案して編集可能にする**。

### 親フォルダは登録制（毎回の参照ダイアログを避ける）

**フォルダ参照ダイアログを既定の動線にしない。** 毎回、関係ないフォルダの中から
目的地を探すことになり手間がかかる。

- よく使う親フォルダを登録し、`[Z6] [Z50] [ + ]` のように1クリックで切り替える
- 初期状態は登録ゼロで `[ + ]` のみ。`[ + ]` を押したときだけ参照ダイアログを出す
- ボタンのラベルはフォルダ名の末尾。同名が衝突したら1つ上の階層まで含める
- 選択中の親は**フルパスを併記**する（どこを指しているか常に見えるようにする）
- **登録の削除で実フォルダを消さない**（削除機能は GUI に持たない / §7）
- 登録は `config.toml` に保存する
