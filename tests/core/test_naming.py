"""photolab/core/naming.py のテスト。

命名規則は architecture.md §5.2 と計画書 §3.2 が仕様。
    YYYYMMDD-hhmmss_NN.<拡張子>   NN は秒内連番（2桁、01 始まり）
"""

from datetime import datetime

import pytest

from photolab.core.naming import (
    SequenceOverflowError,
    Shot,
    assign_basenames,
    format_basename,
)


def shot(hhmmss, shutter_count=None, source_name="DSC_0001.NEF"):
    """テスト用の Shot を簡潔に作る。日付は 2026-07-11 固定。"""
    h, m, s = hhmmss
    return Shot(
        captured_at=datetime(2026, 7, 11, h, m, s),
        shutter_count=shutter_count,
        source_name=source_name,
    )


class TestFormatBasename:
    def test_単一カットは連番01になる(self):
        assert format_basename(datetime(2026, 7, 11, 12, 2, 35), 1) == "20260711-120235_01"

    def test_連番は2桁ゼロ埋めになる(self):
        assert format_basename(datetime(2026, 7, 11, 12, 2, 35), 7) == "20260711-120235_07"
        assert format_basename(datetime(2026, 7, 11, 12, 2, 35), 12) == "20260711-120235_12"


class TestAssignBasenames:
    def test_同じ秒の複数カットに連番が振られる(self):
        shots = [shot((12, 2, 35)), shot((12, 2, 35)), shot((12, 2, 35))]
        assert assign_basenames(shots) == [
            "20260711-120235_01",
            "20260711-120235_02",
            "20260711-120235_03",
        ]

    def test_秒が違えばそれぞれ01から始まる(self):
        shots = [shot((12, 2, 35)), shot((12, 2, 36))]
        assert assign_basenames(shots) == [
            "20260711-120235_01",
            "20260711-120236_01",
        ]


class TestAssignOrder:
    """採番順序はショットカウント昇順。取れなければ元ファイル名昇順（計画書 §3.2）。"""

    def test_ショットカウント昇順で採番される(self):
        # 入力順は逆でも、ショットカウントの小さい方が _01 になる
        shots = [
            shot((12, 2, 35), shutter_count=102, source_name="DSC_0002.NEF"),
            shot((12, 2, 35), shutter_count=101, source_name="DSC_0001.NEF"),
        ]
        assert assign_basenames(shots) == [
            "20260711-120235_02",
            "20260711-120235_01",
        ]

    def test_ショットカウントが無ければ元ファイル名昇順になる(self):
        shots = [
            shot((12, 2, 35), shutter_count=None, source_name="DSC_0009.NEF"),
            shot((12, 2, 35), shutter_count=None, source_name="DSC_0002.NEF"),
        ]
        assert assign_basenames(shots) == [
            "20260711-120235_02",
            "20260711-120235_01",
        ]


class TestExistingCollision:
    """出力先の既存ファイルも走査して連番衝突を避ける（計画書 §3.2 / Q2）。"""

    def test_既存の連番は避けて採番される(self):
        existing = ["20260711-120235_01.NEF", "20260711-120235_01.JPG"]
        assert assign_basenames([shot((12, 2, 35))], existing) == ["20260711-120235_02"]

    def test_既存が飛び番でも未使用の最小値から埋める(self):
        existing = ["20260711-120235_01.NEF", "20260711-120235_03.NEF"]
        assert assign_basenames([shot((12, 2, 35)), shot((12, 2, 35))], existing) == [
            "20260711-120235_02",
            "20260711-120235_04",
        ]

    def test_別の秒の既存ファイルは影響しない(self):
        existing = ["20260711-120236_01.NEF"]
        assert assign_basenames([shot((12, 2, 35))], existing) == ["20260711-120235_01"]

    def test_旧形式は連番を消費しない(self):
        # 20191001-091654002.JPG 形式。末尾3桁は秒内連番ではない（計画書 §7）
        existing = ["20260711-120235010.JPG"]
        assert assign_basenames([shot((12, 2, 35))], existing) == ["20260711-120235_01"]


class TestNoCapturedAt:
    """撮影日時が取れないファイル（未対応フォーマット等）はリネームしない。

    日時が無い以上 `YYYYMMDD-hhmmss_NN` は組み立てられない。
    でっち上げた日時を付けるより、元ファイル名のまま取り込んで警告する。
    """

    def test_撮影日時が無ければ元のファイル名を使う(self):
        s = Shot(captured_at=None, shutter_count=None, source_name="IMG_1234.HEIC")
        assert assign_basenames([s]) == ["IMG_1234"]

    def test_撮影日時が無いカットは連番を消費しない(self):
        shots = [
            Shot(captured_at=None, shutter_count=None, source_name="IMG_1234.HEIC"),
            shot((12, 2, 35)),
        ]
        assert assign_basenames(shots) == ["IMG_1234", "20260711-120235_01"]

    def test_拡張子が無い元ファイル名でも動く(self):
        s = Shot(captured_at=None, shutter_count=None, source_name="README")
        assert assign_basenames([s]) == ["README"]


class TestSequenceOverflow:
    """連番は2桁固定。99 を超えたら黙って上書きせずエラーで止める（計画書 §3.2）。"""

    def test_99を超えたらエラーになる(self):
        existing = [f"20260711-120235_{n:02d}.NEF" for n in range(1, 100)]
        with pytest.raises(SequenceOverflowError):
            assign_basenames([shot((12, 2, 35))], existing)

    def test_99番目までは採番できる(self):
        existing = [f"20260711-120235_{n:02d}.NEF" for n in range(1, 99)]
        assert assign_basenames([shot((12, 2, 35))], existing) == ["20260711-120235_99"]
