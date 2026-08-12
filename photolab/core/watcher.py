"""媒体の出現を検出する。

**「前回との差分を返す」だけの薄い層。** タイマーは呼び出し側（`ui/tray.py`）が持つ。

方式はポーリング（architecture.md §5.1）。OS のデバイス到着イベントは
Windows と Linux で API がまったく別物になるため、まずは1本で動くポーリングにする。
イベント駆動にしたくなったら、**この層の中身だけを差し替えれば呼び出し側は変わらない**。

> Windows: `WM_DEVICECHANGE` / Linux: udev モニタ・udisks2 の D-Bus・
> `/media/$USER` の inotify（計画書 §4-Q1-2）

発火条件は `scanner.find_media()` の判定そのもの
（**リムーバブル かつ `DCIM/` がある**）。中身は読まない。
"""

from typing import Callable, Sequence

from photolab.core.scanner import MediaCandidate, find_media


class MediaWatcher:
    """新しく現れた媒体だけを返す。

    挿しっぱなしのカードで毎回発火しないよう、前回見えていた集合を覚えておく。
    抜いたら忘れるので、挿し直せば再び発火する。
    """

    def __init__(self, finder: Callable[[], Sequence[MediaCandidate]] = find_media):
        self._finder = finder
        self._seen: set = set()

    def poll(self) -> tuple[MediaCandidate, ...]:
        """1回分の検出。前回から増えた媒体を返す。

        検出に失敗しても**例外を投げず空を返す**。ドライブが現れた直後は
        ファイルシステムがまだ見えず失敗しうるため、次のポーリングに回す。

        このとき**「抜かれた」とは解釈しない。** 失敗を抜き差しと誤解すると、
        復帰したときに挿しっぱなしのカードで再発火してしまう。
        """
        try:
            found = list(self._finder())
        except OSError:
            return ()

        current = {candidate.root for candidate in found}
        appeared = [c for c in found if c.root not in self._seen]
        self._seen = current
        return tuple(appeared)

    def reset(self) -> None:
        """覚えている媒体を忘れる。挿しっぱなしでも次回また発火する。"""
        self._seen = set()
