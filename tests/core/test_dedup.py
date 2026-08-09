"""photolab/core/dedup.py のテスト。

重複判定キーは architecture.md §5.3 が仕様。カタログの唯一の存在意義であり、
本プロジェクトの技術的な肝。
"""

from datetime import datetime

from photolab.core.dedup import build_key, fallback_key, still_key
from photolab.core.metadata import Metadata


class TestStillKey:
    """静止画: カメラシリアル + ショットカウント。リネームやコピーで壊れない。"""

    def test_シリアルとショットカウントからキーを作る(self):
        assert still_key(serial="2007594", shutter_count=17) == "nikon:2007594:17"

    def test_同じボディの別カットは別キーになる(self):
        assert still_key("2007594", 17) != still_key("2007594", 18)

    def test_別ボディの同じショットカウントは別キーになる(self):
        assert still_key("2007594", 17) != still_key("2021917", 17)


class TestFallbackKey:
    """動画、および MakerNote を取得できなかった静止画の退避キー。

    静止画キーより弱い（カードをフォーマットすると元ファイル名が振り直されるため）。
    使用時は GUI に警告を出す（architecture.md §5.3）。
    """

    def test_撮影日時と元ファイル名とサイズからキーを作る(self):
        key = fallback_key(
            captured_at=datetime(2026, 7, 11, 12, 10, 30),
            source_name="DSC_0114.MOV",
            size=91_336_704,
        )
        assert key == "t:2026-07-11T12:10:30:DSC_0114.MOV:91336704"

    def test_撮影日時が違えば別キーになる(self):
        a = fallback_key(datetime(2026, 7, 11, 12, 10, 30), "DSC_0114.MOV", 100)
        b = fallback_key(datetime(2026, 7, 11, 12, 10, 31), "DSC_0114.MOV", 100)
        assert a != b

    def test_サイズが違えば別キーになる(self):
        a = fallback_key(datetime(2026, 7, 11, 12, 10, 30), "DSC_0114.MOV", 100)
        b = fallback_key(datetime(2026, 7, 11, 12, 10, 30), "DSC_0114.MOV", 101)
        assert a != b

    def test_静止画キーとは前置詞で区別される(self):
        key = fallback_key(datetime(2026, 7, 11, 12, 10, 30), "DSC_0001.NEF", 100)
        assert key.startswith("t:")
        assert not key.startswith("nikon:")


class TestBuildKey:
    """メタデータからどちらのキーを使うか決める。退避したことを呼び出し側に伝える。"""

    def test_シリアルとショットカウントがあれば静止画キーを使う(self):
        meta = Metadata(
            camera_serial="2007594",
            shutter_count=17,
            captured_at=datetime(2018, 12, 12, 20, 0, 22),
        )
        key = build_key(meta, source_name="DSC_0017.NEF", size=32721131)
        assert key.value == "nikon:2007594:17"
        assert key.is_fallback is False

    def test_MakerNoteが無ければ退避キーになる(self):
        meta = Metadata(captured_at=datetime(2019, 1, 2, 15, 38, 47))
        key = build_key(meta, source_name="DSC_0114.MOV", size=91336704)
        assert key.value == "t:2019-01-02T15:38:47:DSC_0114.MOV:91336704"
        # GUI で警告を出すために、退避したことが分かる必要がある
        assert key.is_fallback is True

    def test_ショットカウントだけではシリアル不明なので退避する(self):
        meta = Metadata(shutter_count=17, captured_at=datetime(2018, 12, 12, 20, 0, 22))
        assert build_key(meta, "DSC_0017.NEF", 100).is_fallback is True

    def test_撮影日時もMakerNoteも無ければ名前とサイズのキーになる(self):
        # 未対応フォーマット。リネームせず元ファイル名のまま取り込む（naming 参照）
        key = build_key(Metadata(), source_name="IMG_1234.HEIC", size=4096)
        assert key.value == "n:IMG_1234.HEIC:4096"
        assert key.is_fallback is True

    def test_名前キーは他のキーと前置詞で区別される(self):
        key = build_key(Metadata(), "IMG_1234.HEIC", 4096)
        assert key.value.startswith("n:")
