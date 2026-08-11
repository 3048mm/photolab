"""photolab/core/maintenance.py のテスト。

カタログと実ファイルの食い違いを検出して直す。
**写真そのものは絶対に削除しない**（消すのはカタログの記録だけ）。
"""

import pytest

from photolab.core.catalog import Catalog
from photolab.core.copier import hash_file
from photolab.core.maintenance import check_catalog, remove_missing


@pytest.fixture
def catalog(tmp_path):
    with Catalog(tmp_path / "catalog.db") as c:
        yield c


def add(catalog, tmp_path, key, name, content=b"photo", exists=True):
    """カタログに1件登録する。`exists=False` なら実ファイルを作らない。"""
    folder = tmp_path / "dest"
    folder.mkdir(exist_ok=True)
    path = folder / name
    if exists:
        path.write_bytes(content)
    batch_id = catalog.start_batch("E:", str(folder))
    catalog.record_media(
        dedup_key=key,
        batch_id=batch_id,
        dest_path=str(folder),
        dest_name=name,
        content_hash=hash_file(path) if exists else "dummy",
        file_size=len(content) if exists else 0,
    )
    return path


class TestCheckCatalog:
    def test_実ファイルがあれば問題なし(self, catalog, tmp_path):
        add(catalog, tmp_path, "nikon:1:1", "a.NEF")
        report = check_catalog(catalog)
        assert report.total == 1
        assert report.missing == ()

    def test_実ファイルが無い記録を検出する(self, catalog, tmp_path):
        add(catalog, tmp_path, "nikon:1:1", "a.NEF")
        add(catalog, tmp_path, "nikon:1:2", "b.NEF", exists=False)
        report = check_catalog(catalog)
        assert report.total == 2
        assert [r["dedup_key"] for r in report.missing] == ["nikon:1:2"]

    def test_取り込み後に消されたファイルも検出する(self, catalog, tmp_path):
        path = add(catalog, tmp_path, "nikon:1:1", "a.NEF")
        path.unlink()
        assert len(check_catalog(catalog).missing) == 1

    def test_既定ではハッシュを検証しない(self, catalog, tmp_path):
        path = add(catalog, tmp_path, "nikon:1:1", "a.NEF")
        path.write_bytes(b"changed")
        assert check_catalog(catalog).hash_mismatch == ()

    def test_要求すればハッシュ不一致を検出する(self, catalog, tmp_path):
        path = add(catalog, tmp_path, "nikon:1:1", "a.NEF")
        path.write_bytes(b"changed")
        report = check_catalog(catalog, verify_hash=True)
        assert [r["dedup_key"] for r in report.hash_mismatch] == ["nikon:1:1"]

    def test_問題が無ければokになる(self, catalog, tmp_path):
        add(catalog, tmp_path, "nikon:1:1", "a.NEF")
        assert check_catalog(catalog, verify_hash=True).ok is True


class TestRemoveMissing:
    def test_実ファイルが無い記録だけ消す(self, catalog, tmp_path):
        add(catalog, tmp_path, "nikon:1:1", "a.NEF")
        add(catalog, tmp_path, "nikon:1:2", "b.NEF", exists=False)

        removed = remove_missing(catalog, check_catalog(catalog))

        assert removed == 1
        assert catalog.media_count() == 1
        assert catalog.is_imported("nikon:1:1") is True
        assert catalog.is_imported("nikon:1:2") is False

    def test_写真そのものは消さない(self, catalog, tmp_path):
        path = add(catalog, tmp_path, "nikon:1:1", "a.NEF")
        add(catalog, tmp_path, "nikon:1:2", "b.NEF", exists=False)

        remove_missing(catalog, check_catalog(catalog))

        assert path.is_file()  # 実ファイルには一切触れない

    def test_消したカットは再び未取り込みになる(self, catalog, tmp_path):
        add(catalog, tmp_path, "nikon:1:2", "b.NEF", exists=False)
        remove_missing(catalog, check_catalog(catalog))
        assert catalog.is_imported("nikon:1:2") is False

    def test_問題が無ければ何も消さない(self, catalog, tmp_path):
        add(catalog, tmp_path, "nikon:1:1", "a.NEF")
        assert remove_missing(catalog, check_catalog(catalog)) == 0
        assert catalog.media_count() == 1
