"""photolab/core/scanner.py のテスト。

実機カード（Nikon Z6 / FAT32）の構造を再現した合成データに対して行う。
カードが挿さっていない環境でも動く必要があるため、実カードは使わない。

    L:\\
      ├─ DCIM\\102NCZ_6\\   ← 取り込み対象
      │    ├─ DSC_4590.NEF / .JPG   （RAW+JPEG ペア）
      │    ├─ DSC_4657.JPG          （JPEG 単独。実機カードに実在）
      │    ├─ DSC_4659.MOV
      │    └─ NC_FLLST.DAT          ← 除外
      ├─ NIKON\\Z_6                  ← 除外（DCIM 外）
      ├─ System Volume Information\\ ← 除外
      └─ NIKON001.DSC               ← 除外（DCIM 外）
"""

import pytest

from photolab.core.scanner import MediaCandidate, has_dcim, is_excluded, scan_card


class TestExclusions:
    """カード上に存在するがコピー対象外とするもの（architecture.md §5.5）。"""

    @pytest.mark.parametrize(
        "name",
        [
            "NC_FLLST.DAT",  # Nikon がカードに書く管理ファイル
            "DSC_0001.THM",  # 付随ファイル
            "DSC_0001.LRV",
            "dsc_0001.lrv",  # 大文字小文字を問わない
            "nc_fllst.dat",
        ],
    )
    def test_付随ファイルは除外される(self, tmp_path, name):
        path = tmp_path / name
        path.write_bytes(b"x")
        assert is_excluded(path) is True

    @pytest.mark.parametrize("name", ["DSC_4590.NEF", "DSC_4590.JPG", "DSC_4659.MOV"])
    def test_取り込み対象は除外されない(self, tmp_path, name):
        path = tmp_path / name
        path.write_bytes(b"x")
        assert is_excluded(path) is False

    def test_未知の拡張子は除外される(self, tmp_path):
        # 取り込み対象を許可リストで決める。知らないものは持って行かない
        path = tmp_path / "NIKON001.DSC"
        path.write_bytes(b"x")
        assert is_excluded(path) is True

    def test_隠しファイルは除外される(self, tmp_path):
        path = tmp_path / ".DS_Store"
        path.write_bytes(b"x")
        assert is_excluded(path) is True


def make_card(tmp_path):
    """実機カードの構造を再現したダミー媒体を作る。"""
    dcim = tmp_path / "DCIM" / "102NCZ_6"
    dcim.mkdir(parents=True)
    for name in [
        "DSC_4590.NEF",
        "DSC_4590.JPG",  # RAW+JPEG ペア
        "DSC_4657.JPG",  # JPEG 単独（実機カードに実在）
        "DSC_4659.MOV",
        "NC_FLLST.DAT",  # 除外
    ]:
        (dcim / name).write_bytes(b"x" * 16)

    # DCIM の外（カメラの管理ファイル）。実機カードに実在する
    (tmp_path / "NIKON").mkdir()
    (tmp_path / "NIKON" / "Z_6").write_bytes(b"x")
    (tmp_path / "NIKON001.DSC").write_bytes(b"x" * 512)
    svi = tmp_path / "System Volume Information"
    svi.mkdir()
    (svi / "WPSettings.dat").write_bytes(b"x")
    return tmp_path


class TestScanCard:
    """DCIM 配下だけを対象にし、カット単位にまとめる。"""

    def test_DCIM配下のメディアだけが対象になる(self, tmp_path):
        shots = scan_card(make_card(tmp_path))
        names = sorted(f.name for s in shots for f in s.files)
        assert names == ["DSC_4590.JPG", "DSC_4590.NEF", "DSC_4657.JPG", "DSC_4659.MOV"]

    def test_RAWとJPEGのペアは1カットにまとまる(self, tmp_path):
        shots = scan_card(make_card(tmp_path))
        pair = [s for s in shots if s.source_name.startswith("DSC_4590")]
        assert len(pair) == 1
        assert sorted(f.suffix for f in pair[0].files) == [".JPG", ".NEF"]

    def test_JPEG単独も1カットになる(self, tmp_path):
        shots = scan_card(make_card(tmp_path))
        single = [s for s in shots if s.source_name == "DSC_4657.JPG"]
        assert len(single) == 1
        assert len(single[0].files) == 1

    def test_カット数は3になる(self, tmp_path):
        # ペア1 + JPEG単独1 + MOV1
        assert len(scan_card(make_card(tmp_path))) == 3

    def test_ペアの代表ファイルはRAWになる(self, tmp_path):
        # 重複判定キーと元ファイル名は RAW 側を基準にする
        shots = scan_card(make_card(tmp_path))
        pair = [s for s in shots if s.source_name.startswith("DSC_4590")][0]
        assert pair.source_name == "DSC_4590.NEF"

    def test_DCIMが無ければ空になる(self, tmp_path):
        (tmp_path / "NIKON").mkdir()
        assert scan_card(tmp_path) == []


class TestHasDcim:
    """媒体候補の判定は DCIM/ の有無で行う（architecture.md §5.1）。"""

    def test_DCIMがあれば媒体候補(self, tmp_path):
        (tmp_path / "DCIM").mkdir()
        assert has_dcim(tmp_path) is True

    def test_DCIMが無ければ媒体候補でない(self, tmp_path):
        assert has_dcim(tmp_path) is False


class TestMediaCandidate:
    """検出した媒体の情報。GUI のメディア選択に使う。"""

    def test_ラベルからカードを識別できる(self, tmp_path):
        # 実機カードのボリュームラベルは 'NIKON Z 6' だった
        candidate = MediaCandidate(root=tmp_path, label="NIKON Z 6")
        assert candidate.display_name == "NIKON Z 6 (%s)" % tmp_path

    def test_ラベルが無ければパスだけ表示する(self, tmp_path):
        candidate = MediaCandidate(root=tmp_path, label="")
        assert candidate.display_name == str(tmp_path)
