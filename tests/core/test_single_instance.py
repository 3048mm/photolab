"""photolab/core/single_instance.py のテスト。

常駐を二重に起動すると、同じカードで2回開いてしまう。
ロックファイルに PID を書いて防ぐ（Linux 移管でもそのまま使える方式）。
"""

import os

from photolab.core.single_instance import SingleInstance


class TestAcquire:
    def test_誰も使っていなければ取れる(self, tmp_path):
        with SingleInstance(tmp_path / "watch.lock") as lock:
            assert lock.acquired is True

    def test_取ると自分のPIDが書かれる(self, tmp_path):
        path = tmp_path / "watch.lock"
        with SingleInstance(path):
            assert path.read_text(encoding="utf-8").strip() == str(os.getpid())

    def test_二重には取れない(self, tmp_path):
        path = tmp_path / "watch.lock"
        with SingleInstance(path) as first:
            second = SingleInstance(path)
            assert first.acquired is True
            assert second.acquire() is False

    def test_離すと次が取れる(self, tmp_path):
        path = tmp_path / "watch.lock"
        first = SingleInstance(path)
        first.acquire()
        first.release()

        assert SingleInstance(path).acquire() is True

    def test_使用中のPIDを教えてくれる(self, tmp_path):
        path = tmp_path / "watch.lock"
        with SingleInstance(path):
            assert SingleInstance(path).running_pid() == os.getpid()


class TestStaleLock:
    """強制終了でロックが残っても、次の起動を妨げてはいけない。"""

    def test_死んだPIDのロックは奪える(self, tmp_path):
        path = tmp_path / "watch.lock"
        path.write_text("999999", encoding="utf-8")  # 存在しない PID

        assert SingleInstance(path).acquire() is True

    def test_壊れた内容のロックは奪える(self, tmp_path):
        path = tmp_path / "watch.lock"
        path.write_text("これは PID ではない", encoding="utf-8")

        assert SingleInstance(path).acquire() is True

    def test_空のロックは奪える(self, tmp_path):
        path = tmp_path / "watch.lock"
        path.write_text("", encoding="utf-8")

        assert SingleInstance(path).acquire() is True

    def test_死んだロックのPIDはNoneになる(self, tmp_path):
        path = tmp_path / "watch.lock"
        path.write_text("999999", encoding="utf-8")

        assert SingleInstance(path).running_pid() is None


class TestRelease:
    def test_離すとファイルが消える(self, tmp_path):
        path = tmp_path / "watch.lock"
        lock = SingleInstance(path)
        lock.acquire()
        lock.release()
        assert not path.exists()

    def test_取っていないのに離しても壊れない(self, tmp_path):
        SingleInstance(tmp_path / "watch.lock").release()

    def test_他人のロックは消さない(self, tmp_path):
        path = tmp_path / "watch.lock"
        path.write_text(str(os.getpid()), encoding="utf-8")

        SingleInstance(path).release()  # acquire していない

        assert path.exists()

    def test_フォルダが無くても取れる(self, tmp_path):
        assert SingleInstance(tmp_path / "a" / "b" / "watch.lock").acquire() is True
