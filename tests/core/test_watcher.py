"""photolab/core/watcher.py のテスト。

「前回との差分を返す」だけの薄い層。タイマーは呼び出し側が持つので、
ここはポーリング1回分の判断だけをテストする。
"""

from pathlib import Path

from photolab.core.scanner import MediaCandidate
from photolab.core.watcher import MediaWatcher


def card(letter: str, label: str = "NIKON Z 6") -> MediaCandidate:
    return MediaCandidate(root=Path(f"{letter}:\\"), label=label)


class FakeFinder:
    """`find_media()` の差し替え。挿さっている媒体を自由に変える。"""

    def __init__(self, *media):
        self.media = list(media)

    def __call__(self):
        return list(self.media)


class TestPoll:
    def test_最初のポーリングで挿さっていれば検出する(self):
        watcher = MediaWatcher(FakeFinder(card("L")))
        assert [m.root for m in watcher.poll()] == [Path("L:\\")]

    def test_挿さっていなければ何も返さない(self):
        assert MediaWatcher(FakeFinder()).poll() == ()

    def test_挿しっぱなしでは再発火しない(self):
        watcher = MediaWatcher(FakeFinder(card("L")))
        assert len(watcher.poll()) == 1
        assert watcher.poll() == ()
        assert watcher.poll() == ()

    def test_抜いて挿し直すと再び発火する(self):
        finder = FakeFinder(card("L"))
        watcher = MediaWatcher(finder)
        assert len(watcher.poll()) == 1

        finder.media = []
        assert watcher.poll() == ()  # 抜いた

        finder.media = [card("L")]
        assert len(watcher.poll()) == 1  # 挿し直した

    def test_後から挿した分だけ返す(self):
        finder = FakeFinder(card("L"))
        watcher = MediaWatcher(finder)
        watcher.poll()

        finder.media = [card("L"), card("E")]
        assert [m.root for m in watcher.poll()] == [Path("E:\\")]

    def test_同時に複数挿さっていれば両方返す(self):
        watcher = MediaWatcher(FakeFinder(card("L"), card("E")))
        assert len(watcher.poll()) == 2

    def test_1台抜いても残りは再発火しない(self):
        finder = FakeFinder(card("L"), card("E"))
        watcher = MediaWatcher(finder)
        watcher.poll()

        finder.media = [card("L")]
        assert watcher.poll() == ()


class TestRobustness:
    """ドライブが現れた直後はファイルシステムがまだ見えないことがある。"""

    def test_検出に失敗しても例外を投げない(self):
        def broken():
            raise OSError("デバイスの準備ができていません")

        assert MediaWatcher(broken).poll() == ()

    def test_失敗の次のポーリングで検出できる(self):
        state = {"fail": True}

        def flaky():
            if state["fail"]:
                raise OSError("まだ準備できていない")
            return [card("L")]

        watcher = MediaWatcher(flaky)
        assert watcher.poll() == ()

        state["fail"] = False
        assert len(watcher.poll()) == 1

    def test_失敗を抜き差しと誤解しない(self):
        # 一時的な失敗で「抜かれた」と判断すると、復帰時に再発火してしまう
        state = {"fail": False}

        def flaky():
            if state["fail"]:
                raise OSError("一時的な失敗")
            return [card("L")]

        watcher = MediaWatcher(flaky)
        assert len(watcher.poll()) == 1

        state["fail"] = True
        assert watcher.poll() == ()

        state["fail"] = False
        assert watcher.poll() == ()  # 挿しっぱなしなので発火しない


class TestReset:
    def test_忘れさせると再び発火する(self):
        watcher = MediaWatcher(FakeFinder(card("L")))
        watcher.poll()
        watcher.reset()
        assert len(watcher.poll()) == 1
