"""photolab/core/thumbnail.py のテスト。

NEF は埋め込み JPEG プレビュー、JPG は自身をデコードして縮小する
（architecture.md §5.4）。フルデコード（デモザイク）は行わない。
"""

import pytest

from photolab.core.thumbnail import (
    DEFAULT_MAX_SIZE,
    ThumbnailCache,
    jpeg_dimensions,
    thumbnail_bytes,
)


@pytest.mark.fixtures
class TestThumbnailBytes:
    def test_NEFからサムネイルを作れる(self, fixtures):
        data = thumbnail_bytes(fixtures / "DSC_0017.NEF")
        assert data is not None
        assert data[:2] == b"\xff\xd8"  # JPEG

    def test_JPGからサムネイルを作れる(self, fixtures):
        data = thumbnail_bytes(fixtures / "20260101-084710010.JPG")
        assert data is not None
        assert data[:2] == b"\xff\xd8"

    def test_長辺が指定サイズ以下になる(self, fixtures):
        data = thumbnail_bytes(fixtures / "DSC_0017.NEF", max_size=256)
        assert max(jpeg_dimensions(data)) <= 256

    def test_元画像より十分小さくなる(self, fixtures):
        src = fixtures / "20260101-084710010.JPG"
        data = thumbnail_bytes(src)
        assert len(data) < src.stat().st_size / 10

    def test_縦横比が保たれる(self, fixtures):
        # Z6 は 3:2
        width, height = jpeg_dimensions(thumbnail_bytes(fixtures / "DSC_0017.NEF"))
        assert width / height == pytest.approx(3 / 2, rel=0.02)

    def test_MOVからもサムネイルを作れる(self, fixtures):
        # Nikon の MOV は moov/udta/NCDT に JPEG を埋め込んでいる（§5.4）
        data = thumbnail_bytes(fixtures / "DSC_0114.MOV")
        assert data is not None
        assert data[:2] == b"\xff\xd8"

    def test_MOVのサムネイルも指定サイズ以下になる(self, fixtures):
        data = thumbnail_bytes(fixtures / "DSC_0114.MOV", max_size=256)
        assert max(jpeg_dimensions(data)) <= 256

    def test_動画以外の未対応拡張子はNoneを返す(self, tmp_path):
        path = tmp_path / "NIKON001.DSC"
        path.write_bytes(b"x" * 32)
        assert thumbnail_bytes(path) is None


class TestRobustness:
    """1枚の異常でグリッド全体を落とさない。"""

    def test_壊れたNEFでも例外を投げない(self, tmp_path):
        path = tmp_path / "broken.NEF"
        path.write_bytes(b"II*\x00" + b"\xff" * 64)
        assert thumbnail_bytes(path) is None

    def test_壊れたJPGでも例外を投げない(self, tmp_path):
        path = tmp_path / "broken.JPG"
        path.write_bytes(b"\xff\xd8" + b"\x00" * 64)
        assert thumbnail_bytes(path) is None

    def test_存在しないファイルでも例外を投げない(self, tmp_path):
        assert thumbnail_bytes(tmp_path / "missing.NEF") is None


@pytest.mark.fixtures
class TestThumbnailCache:
    def test_1回目でキャッシュファイルが作られる(self, tmp_path, fixtures):
        cache = ThumbnailCache(tmp_path)
        assert cache.get(fixtures / "DSC_0017.NEF") is not None
        assert list(tmp_path.iterdir())

    def test_2回目は同じ内容を返す(self, tmp_path, fixtures):
        cache = ThumbnailCache(tmp_path)
        src = fixtures / "DSC_0017.NEF"
        assert cache.get(src) == cache.get(src)

    def test_2回目は元ファイルを読まない(self, tmp_path, fixtures, monkeypatch):
        cache = ThumbnailCache(tmp_path)
        src = fixtures / "DSC_0017.NEF"
        cache.get(src)

        import photolab.core.thumbnail as module

        monkeypatch.setattr(
            module, "thumbnail_bytes", lambda *a, **kw: pytest.fail("再生成された")
        )
        assert cache.get(src) is not None

    def test_サイズ違いは別のキャッシュになる(self, tmp_path, fixtures):
        cache = ThumbnailCache(tmp_path)
        src = fixtures / "DSC_0017.NEF"
        small = cache.get(src, max_size=128)
        large = cache.get(src, max_size=DEFAULT_MAX_SIZE)
        assert small != large
        assert len(list(tmp_path.iterdir())) == 2

    def test_サムネイルを作れないファイルはNoneを返す(self, tmp_path):
        unsupported = tmp_path / "NIKON001.DSC"
        unsupported.write_bytes(b"x" * 32)
        cache = ThumbnailCache(tmp_path / "cache")
        assert cache.get(unsupported) is None

    def test_MOVもキャッシュされる(self, tmp_path, fixtures):
        cache = ThumbnailCache(tmp_path)
        src = fixtures / "DSC_0114.MOV"
        assert cache.get(src) is not None
        assert cache.get(src) == cache.get(src)


@pytest.mark.fixtures
class TestGenerateMany:
    """読み出しは直列、縮小だけ並列にする（実測の根拠は docstring 参照）。"""

    def test_渡した全ファイル分の結果が返る(self, tmp_path, fixtures):
        paths = [
            fixtures / "DSC_0017.NEF",
            fixtures / "20260101-084710010.JPG",
            fixtures / "DSC_0114.MOV",
        ]
        result = ThumbnailCache(tmp_path).generate_many(paths)
        assert set(result) == set(paths)

    def test_動画からもサムネイルが返る(self, tmp_path, fixtures):
        paths = [fixtures / "DSC_0114.MOV"]
        assert ThumbnailCache(tmp_path).generate_many(paths)[paths[0]] is not None

    def test_未対応ファイルはNoneになる(self, tmp_path):
        unsupported = tmp_path / "NIKON001.DSC"
        unsupported.write_bytes(b"x" * 32)
        result = ThumbnailCache(tmp_path / "cache").generate_many([unsupported])
        assert result[unsupported] is None

    def test_単体生成と同じ結果になる(self, tmp_path, fixtures):
        src = fixtures / "DSC_0017.NEF"
        one = ThumbnailCache(tmp_path / "a").get(src)
        many = ThumbnailCache(tmp_path / "b").generate_many([src])[src]
        assert one == many

    def test_2回目はキャッシュから返る(self, tmp_path, fixtures, monkeypatch):
        cache = ThumbnailCache(tmp_path)
        paths = [fixtures / "DSC_0017.NEF"]
        cache.generate_many(paths)

        import photolab.core.thumbnail as module

        monkeypatch.setattr(
            module, "_embedded_preview", lambda *a: pytest.fail("再読み込みされた")
        )
        assert cache.generate_many(paths)[paths[0]] is not None
