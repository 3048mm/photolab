"""重複判定キーの生成。

カタログが答えるのは「このカットは取り込み済みか？」の1問だけであり
（architecture.md §3.3）、その判定に使うキーをここで組み立てる。

| 種別 | キー | 形式 |
| :--- | :--- | :--- |
| 静止画 | カメラシリアル + ショットカウント | `nikon:{serial}:{shutter_count}` |
| 動画   | 撮影日時 + 元ファイル名 + サイズ | `t:{captured_at}:{source_name}:{size}` |

Nikon の MakerNote に含まれるシリアル番号 + ショットカウントはボディごとに
完全に一意で、リネームやコピーでも壊れない。カードをフォーマットせず使い回しても、
別カードに同じカットが入っていても正しく判定できる（architecture.md §5.3）。
"""


from dataclasses import dataclass
from datetime import datetime

from photolab.core.metadata import Metadata


@dataclass(frozen=True)
class DedupKey:
    """重複判定キーと、それが退避キーかどうか。

    `is_fallback` が True のカットは GUI で警告する（architecture.md §5.3）。
    """

    value: str
    is_fallback: bool


def still_key(serial: str, shutter_count: int) -> str:
    """静止画の重複判定キー。"""
    return f"nikon:{serial}:{shutter_count}"


def fallback_key(captured_at: datetime, source_name: str, size: int) -> str:
    """動画、および MakerNote を取得できなかった静止画の退避キー。

    静止画キーより弱い。カードをフォーマットするとカメラが `DSC_0001` から
    振り直すため、別カットが同名・同秒・同サイズになる可能性がゼロではない。
    **このキーを使ったカットは GUI で警告する**（architecture.md §5.3）。
    """
    return f"t:{captured_at.isoformat()}:{source_name}:{size}"


def name_key(source_name: str, size: int) -> str:
    """撮影日時すら取れないファイルの最終手段のキー。

    未対応フォーマットを想定している。3つのキーの中で最も弱い
    （カードをフォーマットすると元ファイル名が振り直されるため、
    同名・同サイズの別ファイルを取り込み済みと誤判定しうる）。
    """
    return f"n:{source_name}:{size}"


def build_key(meta: Metadata, source_name: str, size: int) -> DedupKey:
    """メタデータからどちらのキーを使うか決める。

    強い順に3段階へ落ちる。`is_fallback` が True のカットは GUI で警告する。

    | 条件 | キー | 形式 |
    | :--- | :--- | :--- |
    | シリアル + ショットカウントあり | 静止画キー | `nikon:{serial}:{count}` |
    | 撮影日時あり（動画・MakerNote 無し） | 退避キー | `t:{captured_at}:{name}:{size}` |
    | 撮影日時も無し（未対応フォーマット） | 名前キー | `n:{name}:{size}` |
    """
    if meta.has_still_key:
        # has_still_key が True なら両方 None でないことが保証される
        assert meta.camera_serial is not None and meta.shutter_count is not None
        return DedupKey(still_key(meta.camera_serial, meta.shutter_count), is_fallback=False)

    if meta.captured_at is None:
        # 未対応フォーマット等で撮影日時すら取れない場合。
        # この種のファイルはリネームせず元ファイル名のまま取り込む（core/naming.py）。
        return DedupKey(name_key(source_name, size), is_fallback=True)

    return DedupKey(fallback_key(meta.captured_at, source_name, size), is_fallback=True)
