"""photolab/core/catalog.py のテスト。

スキーマは architecture.md §9。カタログが答えるのは
「このカットは取り込み済みか？」の1問だけ（§3.3）。
"""

from datetime import datetime

from photolab.core.catalog import Catalog


def open_catalog(tmp_path):
    """テスト用に一時ファイルのカタログを開く。"""
    return Catalog(tmp_path / "catalog.db")


class TestSchema:
    def test_開くとスキーマが作られる(self, tmp_path):
        with open_catalog(tmp_path) as catalog:
            tables = catalog.table_names()
        assert {"import_batch", "imported_media", "schema_version"} <= tables

    def test_既存のカタログを開き直せる(self, tmp_path):
        path = tmp_path / "catalog.db"
        with Catalog(path) as catalog:
            catalog.start_batch(source_label="E:", dest_root=r"D:\tmp")
        with Catalog(path) as catalog:
            assert "imported_media" in catalog.table_names()

    def test_スキーマバージョンが記録される(self, tmp_path):
        with open_catalog(tmp_path) as catalog:
            assert catalog.schema_version() == Catalog.SCHEMA_VERSION


class TestBatch:
    def test_バッチを開始すると実行中になる(self, tmp_path):
        with open_catalog(tmp_path) as catalog:
            batch_id = catalog.start_batch(source_label="E:", dest_root=r"D:\tmp")
            assert catalog.batch_status(batch_id) == "running"

    def test_バッチを完了できる(self, tmp_path):
        with open_catalog(tmp_path) as catalog:
            batch_id = catalog.start_batch("E:", r"D:\tmp")
            catalog.finish_batch(batch_id, file_count=3)
            assert catalog.batch_status(batch_id) == "done"

    def test_バッチを中断として記録できる(self, tmp_path):
        with open_catalog(tmp_path) as catalog:
            batch_id = catalog.start_batch("E:", r"D:\tmp")
            catalog.abort_batch(batch_id, file_count=1)
            assert catalog.batch_status(batch_id) == "aborted"


def record(catalog, batch_id, dedup_key, dest_path=r"D:\tmp", dest_name="a.NEF", **kw):
    """テスト用に1件登録する。"""
    return catalog.record_media(
        dedup_key=dedup_key,
        batch_id=batch_id,
        dest_path=dest_path,
        dest_name=dest_name,
        **kw,
    )


class TestImportedQuery:
    """カタログが答えるのは「このカットは取り込み済みか？」の1問だけ（§3.3）。"""

    def test_登録していないキーは取り込み済みでない(self, tmp_path):
        with open_catalog(tmp_path) as catalog:
            assert catalog.is_imported("nikon:2007594:17") is False

    def test_登録したキーは取り込み済みになる(self, tmp_path):
        with open_catalog(tmp_path) as catalog:
            batch_id = catalog.start_batch("E:", r"D:\tmp")
            record(catalog, batch_id, "nikon:2007594:17")
            assert catalog.is_imported("nikon:2007594:17") is True

    def test_複数キーの取り込み済みを一括で問い合わせできる(self, tmp_path):
        # GUI のサムネイルグリッドが1枚ずつ問い合わせずに済むようにする
        with open_catalog(tmp_path) as catalog:
            batch_id = catalog.start_batch("E:", r"D:\tmp")
            record(catalog, batch_id, "nikon:2007594:17")
            record(catalog, batch_id, "nikon:2007594:18", dest_name="b.NEF")
            found = catalog.imported_keys(
                ["nikon:2007594:17", "nikon:2007594:19", "nikon:2007594:18"]
            )
        assert found == {"nikon:2007594:17", "nikon:2007594:18"}

    def test_問い合わせが空なら空集合を返す(self, tmp_path):
        with open_catalog(tmp_path) as catalog:
            assert catalog.imported_keys([]) == set()


class TestUpsert:
    """再取り込みは UPSERT。履歴は持たず dest_path を上書きする（Q3 合意）。"""

    def test_同じキーの再登録でレコードは増えない(self, tmp_path):
        with open_catalog(tmp_path) as catalog:
            batch_id = catalog.start_batch("E:", r"D:\tmp")
            record(catalog, batch_id, "nikon:2007594:17")
            record(catalog, batch_id, "nikon:2007594:17")
            assert catalog.media_count() == 1

    def test_再登録でコピー先が更新される(self, tmp_path):
        with open_catalog(tmp_path) as catalog:
            batch_id = catalog.start_batch("E:", r"D:\tmp")
            record(catalog, batch_id, "nikon:2007594:17", dest_path=r"D:\old")
            record(catalog, batch_id, "nikon:2007594:17", dest_path=r"D:\new")
            assert catalog.find("nikon:2007594:17")["dest_path"] == r"D:\new"

    def test_退避キーであることを記録できる(self, tmp_path):
        # GUI の警告表示と、後からの棚卸しに使う
        with open_catalog(tmp_path) as catalog:
            batch_id = catalog.start_batch("E:", r"D:\tmp")
            record(catalog, batch_id, "t:2019-01-02T15:38:47:DSC_0114.MOV:100", is_fallback=True)
            row = catalog.find("t:2019-01-02T15:38:47:DSC_0114.MOV:100")
            assert row["is_fallback"] == 1

    def test_メタデータを保存できる(self, tmp_path):
        with open_catalog(tmp_path) as catalog:
            batch_id = catalog.start_batch("E:", r"D:\tmp")
            record(
                catalog,
                batch_id,
                "nikon:2007594:17",
                camera_model="NIKON Z 6",
                camera_serial="2007594",
                shutter_count=17,
                captured_at=datetime(2018, 12, 12, 20, 0, 22),
                source_name="DSC_0017.NEF",
                file_size=32721131,
                content_hash="abc123",
            )
            row = catalog.find("nikon:2007594:17")
        assert row["camera_model"] == "NIKON Z 6"
        assert row["shutter_count"] == 17
        assert row["captured_at"] == "2018-12-12T20:00:22"
        assert row["content_hash"] == "abc123"
