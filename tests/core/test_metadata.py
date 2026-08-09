"""photolab/core/metadata.py のテスト。

実データ（`data/test/`）に対して行う。仕様は architecture.md §5.3。
"""

from datetime import datetime

import pytest

from photolab.core.metadata import Metadata, read_metadata


@pytest.mark.fixtures
class TestReadNef:
    """NEF は素の TIFF。Nikon MakerNote から serial / shutter_count を取る。"""

    def test_Z6のNEFからメタデータを取得できる(self, fixtures):
        meta = read_metadata(fixtures / "DSC_0017.NEF")
        assert meta.camera_model == "NIKON Z 6"
        assert meta.camera_serial == "2007594"
        assert meta.shutter_count == 17
        assert meta.captured_at == datetime(2018, 12, 12, 20, 0, 22)

    def test_Z50のNEFからメタデータを取得できる(self, fixtures):
        meta = read_metadata(fixtures / "20260315-163434010.NEF")
        assert meta.camera_model == "NIKON Z 50"
        assert meta.camera_serial == "2021917"
        assert meta.shutter_count == 1817
        assert meta.captured_at == datetime(2026, 3, 15, 16, 34, 34)


@pytest.mark.fixtures
class TestReadJpeg:
    """Z50 は JPEG 中心のため、JPG 単独カットも一級市民（architecture.md §5.4）。"""

    def test_JPGからもメタデータを取得できる(self, fixtures):
        meta = read_metadata(fixtures / "20260101-084710010.JPG")
        assert meta.camera_model == "NIKON Z 50"
        assert meta.camera_serial == "2021917"
        assert meta.shutter_count == 1133
        assert meta.captured_at == datetime(2026, 1, 1, 8, 47, 10)

    def test_RAWとJPEGのペアは同じ値を返す(self, fixtures):
        nef = read_metadata(fixtures / "DSC_0017.NEF")
        jpg = read_metadata(fixtures / "DSC_0017.JPG")
        # この一致が RAW+JPEG ペアを1カットとして扱える根拠になる
        assert (nef.camera_serial, nef.shutter_count) == (jpg.camera_serial, jpg.shutter_count)
        assert nef.captured_at == jpg.captured_at


@pytest.mark.fixtures
class TestReadVideo:
    """MOV は mvhd の creation_time。ローカル時刻なので変換不要（§5.2）。"""

    def test_MOVから撮影日時を取得できる(self, fixtures):
        meta = read_metadata(fixtures / "DSC_0114.MOV")
        assert meta.captured_at == datetime(2019, 1, 2, 15, 38, 47)

    def test_MOVはシリアルとショットカウントを持たない(self, fixtures):
        meta = read_metadata(fixtures / "DSC_0114.MOV")
        assert meta.camera_serial is None
        assert meta.shutter_count is None
        assert meta.has_still_key is False


class TestRobustness:
    """1枚の異常で取り込みバッチ全体を落とさない。例外ではなく空の Metadata を返す。"""

    def test_未対応の拡張子は空のメタデータを返す(self, tmp_path):
        path = tmp_path / "NC_FLLST.DAT"
        path.write_bytes(b"\x00" * 32)
        assert read_metadata(path) == Metadata()

    def test_壊れたNEFでも例外を投げない(self, tmp_path):
        path = tmp_path / "broken.NEF"
        path.write_bytes(b"II*\x00" + b"\xff" * 64)  # TIFF ヘッダだけ本物
        assert read_metadata(path).has_still_key is False

    def test_空ファイルでも例外を投げない(self, tmp_path):
        path = tmp_path / "empty.JPG"
        path.write_bytes(b"")
        assert read_metadata(path) == Metadata()

    def test_存在しないファイルは空のメタデータを返す(self, tmp_path):
        assert read_metadata(tmp_path / "missing.NEF") == Metadata()
