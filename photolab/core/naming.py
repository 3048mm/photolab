"""取り込みファイルの命名。

命名規則（architecture.md §5.2 / 計画書 §3.2）:

    YYYYMMDD-hhmmss_NN.<拡張子>     例: 20260711-120235_01.NEF

`NN` は秒内連番。Z6/Z50 は連写で秒 10 コマを超えるため、秒解像度では必ず衝突する。
"""

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Sequence

# 連番の桁数。秒間 100 コマを撮れるカメラは存在しないため 2 桁で足りる。
SEQ_DIGITS = 2

# 新形式の basename。既存資産の旧形式 `YYYYMMDD-hhmmssNNN`（アンダースコアなし）とは
# アンダースコアの有無で区別でき、文字列衝突しない。旧形式の末尾3桁は秒内連番ではない
# ため（取り込みバッチ単位で一定 / 計画書 §7）、連番の消費対象に含めない。
_BASENAME_RE = re.compile(r"^(\d{8}-\d{6})_(\d{2})$")

# 2 桁で表現できる最大の連番。
MAX_SEQ = 10**SEQ_DIGITS - 1


class SequenceOverflowError(Exception):
    """同一秒の連番が 2 桁に収まらなかった。

    秒間 100 コマを撮れるカメラは存在しないため、ここに到達したら
    メタデータの異常か実装のバグである。黙って上書きせず停止する。
    """


@dataclass(frozen=True)
class Shot:
    """取り込み対象の 1 カット。

    RAW + JPEG のペアは 1 カットとして扱い、同じ basename を共有する
    （architecture.md §5.2）。
    """

    captured_at: datetime
    shutter_count: int | None
    source_name: str


def format_basename(captured_at: datetime, seq: int) -> str:
    """撮影日時と秒内連番から拡張子なしのファイル名を組み立てる。"""
    return f"{captured_at:%Y%m%d-%H%M%S}_{seq:0{SEQ_DIGITS}d}"


def _order_key(shot: Shot) -> tuple:
    """秒内の採番順序。ショットカウント昇順 → 取れなければ元ファイル名昇順。

    ショットカウントを持つカットを先に並べる（撮影順が確実に分かるため）。
    """
    if shot.shutter_count is None:
        return (1, 0, shot.source_name)
    return (0, shot.shutter_count, shot.source_name)


def used_sequences(existing_names: Iterable[str]) -> dict[str, set[int]]:
    """既存ファイル名から「時刻部分 -> 使用済み連番」を集計する。

    拡張子は無視する。RAW + JPEG ペアは同じ basename を共有するため、
    同じ連番が複数回現れるのは正常。
    """
    used: dict[str, set[int]] = defaultdict(set)
    for name in existing_names:
        stem = name.rsplit(".", 1)[0]
        matched = _BASENAME_RE.match(stem)
        if matched:
            used[matched.group(1)].add(int(matched.group(2)))
    return used


def assign_basenames(
    shots: Sequence[Shot], existing_names: Iterable[str] = ()
) -> list[str]:
    """カット列に basename を割り当てる。**入力と同じ順序で**返す。

    採番は秒ごとに独立して 01 から始まり、`existing_names`（出力先フォルダに
    既にあるファイル名）が使用済みの番号は飛ばす。同じ秒に複数カットがある場合の
    順序は `_order_key` に従うため、入力の並びには依存しない。
    """
    used = used_sequences(existing_names)

    by_second: dict[datetime, list[int]] = defaultdict(list)
    for index, s in enumerate(shots):
        by_second[s.captured_at].append(index)

    names: list[str | None] = [None] * len(shots)
    for captured_at, indexes in by_second.items():
        indexes.sort(key=lambda i: _order_key(shots[i]))
        taken = used[f"{captured_at:%Y%m%d-%H%M%S}"]
        seq = 0
        for index in indexes:
            seq += 1
            while seq in taken:
                seq += 1
            if seq > MAX_SEQ:
                raise SequenceOverflowError(
                    f"{captured_at:%Y-%m-%d %H:%M:%S} の秒内連番が "
                    f"{MAX_SEQ} を超えました（既存 {len(taken)} 件 / "
                    f"取り込み {len(indexes)} 件）"
                )
            names[index] = format_basename(captured_at, seq)
    return names  # type: ignore[return-value]
