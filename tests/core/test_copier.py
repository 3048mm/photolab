"""photolab/core/copier.py のテスト。

写真データであり、**サイレントな破損は許容しない**（architecture.md §5.6）。
コピー後に xxHash3 で照合する。
"""

import pytest

from photolab.core.copier import (
    DestinationExistsError,
    HashMismatchError,
    copy_with_verify,
    hash_file,
)


class TestHashFile:
    def test_同じ内容なら同じハッシュになる(self, tmp_path):
        a = tmp_path / "a.bin"
        b = tmp_path / "b.bin"
        a.write_bytes(b"photolab" * 1000)
        b.write_bytes(b"photolab" * 1000)
        assert hash_file(a) == hash_file(b)

    def test_1バイト違えば別のハッシュになる(self, tmp_path):
        a = tmp_path / "a.bin"
        b = tmp_path / "b.bin"
        a.write_bytes(b"photolab" * 1000)
        b.write_bytes(b"photolab" * 999 + b"photolaB")
        assert hash_file(a) != hash_file(b)

    def test_空ファイルでもハッシュを返す(self, tmp_path):
        path = tmp_path / "empty.bin"
        path.write_bytes(b"")
        assert hash_file(path)


class TestCopyWithVerify:
    def test_コピーされて内容が一致する(self, tmp_path):
        src = tmp_path / "DSC_0001.NEF"
        src.write_bytes(b"raw-data" * 5000)
        dest = tmp_path / "out" / "20260711-120235_01.NEF"

        copy_with_verify(src, dest)

        assert dest.read_bytes() == src.read_bytes()

    def test_コピー先のハッシュを返す(self, tmp_path):
        src = tmp_path / "DSC_0001.NEF"
        src.write_bytes(b"raw-data" * 5000)
        dest = tmp_path / "out" / "copied.NEF"

        assert copy_with_verify(src, dest) == hash_file(src)

    def test_コピー先のフォルダが無ければ作る(self, tmp_path):
        src = tmp_path / "DSC_0001.NEF"
        src.write_bytes(b"x")
        dest = tmp_path / "a" / "b" / "c.NEF"

        copy_with_verify(src, dest)

        assert dest.is_file()

    def test_コピー先に同名ファイルがあれば上書きしない(self, tmp_path):
        # 原本の保護。連番採番で衝突は避けているが、多層防御として持つ
        src = tmp_path / "DSC_0001.NEF"
        src.write_bytes(b"new")
        dest = tmp_path / "existing.NEF"
        dest.write_bytes(b"original")

        with pytest.raises(DestinationExistsError):
            copy_with_verify(src, dest)

        assert dest.read_bytes() == b"original"

    def test_更新日時が保持される(self, tmp_path):
        src = tmp_path / "DSC_0001.NEF"
        src.write_bytes(b"x" * 100)
        dest = tmp_path / "out.NEF"

        copy_with_verify(src, dest)

        assert dest.stat().st_mtime == pytest.approx(src.stat().st_mtime, abs=1)


class TestCorruption:
    """サイレントな破損は許容しない（architecture.md §5.6）。"""

    @staticmethod
    def corrupt_after_write(monkeypatch, copier):
        """書き込み直後に1バイト化ける状況を再現する（転送中の破損）。

        コピー元のハッシュは正しく返るが、コピー先の中身だけが食い違う。
        """
        original = copier._copy_and_hash

        def broken(src, dest):
            source_hash = original(src, dest)
            with open(dest, "r+b") as f:
                f.write(b"!")
            return source_hash

        monkeypatch.setattr(copier, "_copy_and_hash", broken)

    def test_破損したコピーを検出する(self, tmp_path, monkeypatch):
        from photolab.core import copier

        self.corrupt_after_write(monkeypatch, copier)
        src = tmp_path / "DSC_0001.NEF"
        src.write_bytes(b"raw-data" * 5000)

        with pytest.raises(HashMismatchError):
            copy_with_verify(src, tmp_path / "out.NEF")

    def test_破損したコピーは残さない(self, tmp_path, monkeypatch):
        # 正常な名前で壊れたファイルが残る方が、写真の資産としては危険
        from photolab.core import copier

        self.corrupt_after_write(monkeypatch, copier)
        src = tmp_path / "DSC_0001.NEF"
        src.write_bytes(b"raw-data" * 5000)
        dest = tmp_path / "out.NEF"

        with pytest.raises(HashMismatchError):
            copy_with_verify(src, dest)

        assert not dest.exists()
