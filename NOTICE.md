# サードパーティライセンス

Photolab 本体は MIT ライセンス（`LICENSE`）。
**製品コードに GPL ライセンスの依存を含めない**方針で依存を選定している
（計画書 `doc/in_progress/importer_plan.md` §4-Q8）。

## 製品コードの依存（`requirements.txt`）

| パッケージ | ライセンス | 備考 |
| :--- | :--- | :--- |
| PySide6 | LGPLv3 / 商用 | Qt Company 公式バインディング。**動的リンクのまま使う**（同梱時も再リンク可能な形を保つ）。GPL である PyQt5/6 は採用しない |
| rawpy | MIT | 同梱される LibRaw は LGPL-2.1 / CDDL-1.0 のデュアルライセンス |
| xxhash | BSD-2-Clause | |

## 開発時のみの依存（`requirements-dev.txt`）

| パッケージ | ライセンス | 備考 |
| :--- | :--- | :--- |
| pytest | MIT | |
| **pyexiv2** | **GPL-3.0** | **配布物・製品コードに含めてはならない。** `photolab/` 配下から import しないこと。`photolab/core/metadata.py` の自前パーサが正しい値を返すかを検証する用途にのみ使う（`tmp/probe_exif.py`） |

## 自前実装で GPL 依存を回避している箇所

EXIF / Nikon MakerNote / QuickTime `mvhd` の解析は `photolab/core/metadata.py` に
標準ライブラリのみで実装している。これにより `pyexiv2`（GPL-3.0）および
`exiv2`（GPL-2.0）への依存を持たない。

## LGPL 準拠についての補足

将来 PyInstaller 等でバイナリ配布する場合、PySide6 (LGPLv3) の条件を満たすには
以下が必要になる。

- Qt を動的リンクのまま保つ（利用者が Qt を差し替えられる状態にする）
- LGPLv3 の全文とライセンス表示を同梱する
- Qt に変更を加えた場合はその差分を提供する

ソースコード配布（GitHub での公開）のみであれば、上記の追加対応は不要。
