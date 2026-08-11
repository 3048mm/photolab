"""photolab/core/importer.py のテスト。

`plan()` は副作用なしでプレビューを返し、`execute()` が実際にコピーする。
GUI のプレビューと CLI のドライランが同じ `plan()` を使う（計画書 §3.5）。

実データのフィクスチャ（`data/test/`）からダミー媒体を組み立てて検証する。
**本番の写真ディレクトリは出力先にしない。**
"""

import shutil

import pytest

from photolab.core.catalog import Catalog
from photolab.core.importer import build_plan, execute, plan
from photolab.core.scanner import scan_card

# ダミー媒体に置くフィクスチャ。RAW+JPEG ペア / RAW 単独 / 動画
CARD_FILES = ["DSC_0017.NEF", "DSC_0017.JPG", "DSC_0018.NEF", "DSC_0114.MOV"]


@pytest.fixture
def card(tmp_path, fixtures):
    """実データから DCIM 構造のダミー媒体を組み立てる。"""
    dcim = tmp_path / "card" / "DCIM" / "100NCZ_6"
    dcim.mkdir(parents=True)
    for name in CARD_FILES:
        shutil.copyfile(fixtures / name, dcim / name)
    (dcim / "NC_FLLST.DAT").write_bytes(b"x" * 16)  # 除外されるはず
    return tmp_path / "card"


@pytest.fixture
def dest(tmp_path):
    return tmp_path / "dest" / "20260809 テスト"


@pytest.fixture
def catalog(tmp_path):
    with Catalog(tmp_path / "catalog.db") as c:
        yield c


@pytest.mark.fixtures
class TestPlan:
    def test_planは副作用を持たない(self, card, dest, catalog):
        plan(card, dest, catalog)
        assert not dest.exists()
        assert catalog.media_count() == 0

    def test_カット数はペアをまとめた数になる(self, card, dest, catalog):
        # DSC_0017(NEF+JPG) / DSC_0018(NEF) / DSC_0114(MOV) = 3 カット
        assert len(plan(card, dest, catalog).shots) == 3

    def test_除外ファイルは含まれない(self, card, dest, catalog):
        sources = [f.source.name for s in plan(card, dest, catalog).shots for f in s.files]
        assert "NC_FLLST.DAT" not in sources

    def test_ペアは同じbasenameを共有する(self, card, dest, catalog):
        result = plan(card, dest, catalog)
        pair = [s for s in result.shots if len(s.files) == 2][0]
        stems = {f.dest.stem for f in pair.files}
        assert len(stems) == 1

    def test_出力先は指定フォルダの直下になる(self, card, dest, catalog):
        result = plan(card, dest, catalog)
        assert all(f.dest.parent == dest for s in result.shots for f in s.files)

    def test_動画は退避キーになり警告対象になる(self, card, dest, catalog):
        result = plan(card, dest, catalog)
        mov = [s for s in result.shots if s.shot.source_name.endswith(".MOV")][0]
        assert mov.dedup_key.is_fallback is True
        assert mov in result.warnings

    def test_静止画は退避キーにならない(self, card, dest, catalog):
        result = plan(card, dest, catalog)
        still = [s for s in result.shots if s.shot.source_name.endswith(".NEF")]
        assert all(s.dedup_key.is_fallback is False for s in still)

    def test_既存ファイルの連番を避ける(self, card, dest, catalog):
        # 先に同じ秒のファイルを置いておく
        result = plan(card, dest, catalog)
        first = [s for s in result.shots if s.shot.source_name == "DSC_0017.NEF"][0]
        dest.mkdir(parents=True)
        (dest / f"{first.basename}.NEF").write_bytes(b"x")

        again = plan(card, dest, catalog)
        retried = [s for s in again.shots if s.shot.source_name == "DSC_0017.NEF"][0]
        assert retried.basename != first.basename
        assert retried.basename.endswith("_02")


@pytest.mark.fixtures
class TestBuildPlan:
    """出力先を変えたら計画を作り直す。カードは読み直さない。"""

    def test_出力先を変えるとコピー先が変わる(self, card, dest, catalog, tmp_path):
        shots = scan_card(card)
        other = tmp_path / "dest" / "別のフォルダ"

        first = build_plan(shots, card, dest, catalog)
        second = build_plan(shots, card, other, catalog)

        assert all(f.dest.parent == dest for s in first.shots for f in s.files)
        assert all(f.dest.parent == other for s in second.shots for f in s.files)

    def test_出力先の既存ファイルに応じて連番が変わる(self, card, dest, catalog):
        shots = scan_card(card)
        first = build_plan(shots, card, dest, catalog)

        # 1カット目と同じ名前のファイルを置いてから作り直す
        dest.mkdir(parents=True)
        (dest / f"{first.shots[0].basename}.NEF").write_bytes(b"x")
        second = build_plan(shots, card, dest, catalog)

        assert second.shots[0].basename != first.shots[0].basename

    def test_カット数と重複判定は変わらない(self, card, dest, catalog, tmp_path):
        shots = scan_card(card)
        first = build_plan(shots, card, dest, catalog)
        second = build_plan(shots, card, tmp_path / "別", catalog)

        assert len(first.shots) == len(second.shots)
        assert [s.dedup_key for s in first.shots] == [s.dedup_key for s in second.shots]


@pytest.mark.fixtures
class TestSplitByDate:
    """日付ごとの振り分け。**既定では行わない**（architecture.md §7）。"""

    def test_既定では1フォルダにまとまる(self, card, dest, catalog):
        result = build_plan(scan_card(card), card, dest, catalog)
        assert result.dest_dirs == (dest,)

    def test_有効にすると日付ごとのフォルダに分かれる(self, card, dest, catalog):
        # フィクスチャは 2018-12-12 の静止画2件と 2019-01-02 の動画1件
        result = build_plan(
            scan_card(card), card, dest, catalog, split_by_date=True
        )
        assert len(result.dest_dirs) > 1
        assert all(d.name[:8].isdigit() for d in result.dest_dirs)

    def test_撮影名を各日付フォルダに付けられる(self, card, dest, catalog):
        result = build_plan(
            scan_card(card), card, dest, catalog,
            split_by_date=True, date_suffix="花火大会",
        )
        assert all(d.name.endswith(" 花火大会") for d in result.dest_dirs)

    def test_撮影名が空なら日付だけのフォルダになる(self, card, dest, catalog):
        # 実際に Z50 の資産が 20260101 のような日付のみのフォルダ名だった
        result = build_plan(scan_card(card), card, dest, catalog, split_by_date=True)
        assert all(len(d.name) == 8 for d in result.dest_dirs)

    def test_振り分け先は指定した親フォルダの直下になる(self, card, dest, catalog):
        result = build_plan(scan_card(card), card, dest, catalog, split_by_date=True)
        assert all(d.parent == dest for d in result.dest_dirs)

    def test_連番はフォルダごとに01から始まる(self, card, dest, catalog):
        result = build_plan(scan_card(card), card, dest, catalog, split_by_date=True)
        for directory in result.dest_dirs:
            in_dir = [s for s in result.shots if s.files[0].dest.parent == directory]
            assert any(s.basename.endswith("_01") for s in in_dir)


@pytest.mark.fixtures
class TestExecute:
    def test_コピーされる(self, card, dest, catalog):
        execute(plan(card, dest, catalog), catalog)
        copied = sorted(p.name for p in dest.iterdir())
        assert len(copied) == 4  # NEF+JPG ペア / NEF / MOV

    def test_カタログに登録される(self, card, dest, catalog):
        execute(plan(card, dest, catalog), catalog)
        assert catalog.media_count() == 3  # カット単位

    def test_バッチが完了として記録される(self, card, dest, catalog):
        result = execute(plan(card, dest, catalog), catalog)
        assert catalog.batch_status(result.batch_id) == "done"

    def test_2回目は全件スキップになる(self, card, dest, catalog):
        execute(plan(card, dest, catalog), catalog)

        second = plan(card, dest, catalog)
        assert all(s.already_imported for s in second.shots)
        assert second.new_shots == ()

    def test_2回目に実行してもコピーされない(self, card, dest, catalog):
        execute(plan(card, dest, catalog), catalog)
        before = sorted(p.name for p in dest.iterdir())

        execute(plan(card, dest, catalog), catalog)

        assert sorted(p.name for p in dest.iterdir()) == before

    def test_ハッシュが記録される(self, card, dest, catalog):
        result = execute(plan(card, dest, catalog), catalog)
        row = catalog.find(result.imported[0].dedup_key.value)
        assert row["content_hash"]
