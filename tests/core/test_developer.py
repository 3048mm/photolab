"""photolab/core/developer.py のテスト。

実際に darktable を起動すると環境に依存するため、`subprocess.Popen` を差し替えて
「何をどう呼ぼうとしたか」を検証する。
"""

from pathlib import Path

import pytest

from photolab.core import developer
from photolab.core.developer import DeveloperNotFoundError, find_darktable, launch


class TestFindDarktable:
    def test_設定されたパスがあればそれを使う(self, tmp_path):
        exe = tmp_path / "darktable.exe"
        exe.write_bytes(b"")
        assert find_darktable(str(exe)) == exe

    def test_設定されたパスが存在しなければNone(self, tmp_path):
        assert find_darktable(str(tmp_path / "missing.exe")) is None


class TestLaunch:
    @pytest.fixture
    def recorded(self, monkeypatch):
        calls = []

        class FakePopen:
            def __init__(self, args, **kwargs):
                calls.append((args, kwargs))

        monkeypatch.setattr(developer.subprocess, "Popen", FakePopen)
        return calls

    @staticmethod
    def _prepare(tmp_path):
        exe = tmp_path / "darktable.exe"
        exe.write_bytes(b"")
        folder = tmp_path / "20260811 テスト"
        folder.mkdir()
        return exe, folder

    def test_実行ファイルと取り込み先を渡して起動する(self, tmp_path, recorded):
        exe, folder = self._prepare(tmp_path)

        launch(folder, configured=str(exe))

        args, _kwargs = recorded[0]
        assert args == [str(exe), str(folder.resolve())]

    def test_相対パスでも絶対パスに直して渡す(self, tmp_path, recorded, monkeypatch):
        # 相対パスのままだと darktable 側の作業ディレクトリ基準で解決され、
        # 存在しないフォルダを渡すことになって何も起きない
        exe, folder = self._prepare(tmp_path)
        monkeypatch.chdir(tmp_path)

        launch(Path(folder.name), configured=str(exe))

        args, _kwargs = recorded[0]
        assert Path(args[1]).is_absolute()
        assert Path(args[1]) == folder.resolve()

    def test_作業ディレクトリを差し替えない(self, tmp_path, recorded):
        # cwd を darktable の場所にすると相対パスの解決先が変わってしまう
        exe, folder = self._prepare(tmp_path)
        launch(folder, configured=str(exe))
        _args, kwargs = recorded[0]
        assert "cwd" not in kwargs or kwargs["cwd"] is None

    def test_フォルダが無ければエラーになる(self, tmp_path, recorded):
        exe = tmp_path / "darktable.exe"
        exe.write_bytes(b"")
        with pytest.raises(FileNotFoundError):
            launch(tmp_path / "missing", configured=str(exe))
        assert recorded == []

    def test_見つからなければエラーになる(self, tmp_path, recorded):
        with pytest.raises(DeveloperNotFoundError):
            launch(tmp_path / "out", configured=str(tmp_path / "missing.exe"))
        assert recorded == []

    def test_実際に渡した値を返す(self, tmp_path, recorded, monkeypatch):
        # 呼び出し側が元の引数をログに出すと、渡した値と表示が食い違う
        exe, folder = self._prepare(tmp_path)
        monkeypatch.chdir(tmp_path)

        returned_exe, returned_folder = launch(Path(folder.name), configured=str(exe))

        args, _kwargs = recorded[0]
        assert (str(returned_exe), str(returned_folder)) == (args[0], args[1])
        assert returned_folder.is_absolute()
