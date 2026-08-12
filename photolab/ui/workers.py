"""ワーカースレッド。

QThread はサブクラス化せず、ワーカーを moveToThread する
（`.claude/skills/photolab-gui/SKILL.md` §2）。

- **sqlite の接続をスレッド間で共有しない。** `Catalog` は run() の中で開いて閉じる
- ワーカーに渡すのは Path / str / dataclass などの不変値だけ
- 例外は握って `failed` シグナルで返す（未捕捉例外はアプリを落とす）
"""

from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from photolab.core.catalog import Catalog
from photolab.core.importer import ImportPlan, execute, plan
from photolab.core.thumbnail import ThumbnailCache, _embedded_preview, render_thumbnail


class PlanWorker(QObject):
    """媒体を走査して取り込み計画を作る。"""

    finished = Signal(object)  # ImportPlan
    failed = Signal(str)

    def __init__(self, source_root: Path, dest_root: Path, catalog_path: Path):
        super().__init__()
        self._source_root = source_root
        self._dest_root = dest_root
        self._catalog_path = catalog_path

    @Slot()
    def run(self) -> None:
        try:
            with Catalog(self._catalog_path) as catalog:
                self.finished.emit(plan(self._source_root, self._dest_root, catalog))
        except Exception as e:
            self.failed.emit(f"メディアの読み取りに失敗しました: {e}")


class ThumbnailWorker(QObject):
    """サムネイルを生成して1件ずつ返す。

    **カードからの読み出しは直列**に保つ（並列読み出しは実測で逆効果 /
    architecture.md §5.4）。縮小だけをスレッドプールに載せる。
    """

    ready = Signal(int, object)  # 行番号, JPEG バイト列（作れなければ None）
    finished = Signal()

    def __init__(self, paths: "list[Path]", cache_dir: Path | None = None, workers: int = 8):
        super().__init__()
        self._paths = list(paths)
        self._cache = ThumbnailCache(cache_dir)
        self._workers = workers
        self._stop = False

    @Slot()
    def stop(self) -> None:
        """媒体を切り替えたときなどに、進行中の生成を打ち切る。"""
        self._stop = True

    @Slot()
    def run(self) -> None:
        from concurrent.futures import ThreadPoolExecutor

        try:
            with ThreadPoolExecutor(max_workers=self._workers) as pool:
                for row, path in enumerate(self._paths):
                    if self._stop:
                        break
                    try:
                        cached = self._cache.path_for(path)
                    except OSError:
                        self.ready.emit(row, None)
                        continue

                    if cached.is_file():
                        self.ready.emit(row, cached.read_bytes())
                        continue

                    try:
                        preview = _embedded_preview(path)  # ここだけが I/O。直列に保つ
                    except Exception:
                        preview = None
                    if preview is None:
                        self.ready.emit(row, None)
                        continue

                    # 縮小は CPU 律速なので別スレッドへ投げ、結果を待って順に返す
                    future = pool.submit(render_thumbnail, preview)
                    data = future.result()
                    if data is not None:
                        self._cache.store(cached, data)
                    self.ready.emit(row, data)
        finally:
            self.finished.emit()


class WatchWorker(QObject):
    """媒体の出現を専用スレッドで見張る。

    **GUI スレッドでファイルシステムに触らないため**にスレッドへ追い出している。
    空のカードスロットや応答しないカードがあると、ドライブの確認だけで
    長く待たされることがあり、そのまま UI が固まる（計画書 §7 / 2026-08-12）。

    タイマーは**このスレッドの中で作る**。GUI スレッドで作ったタイマーを
    moveToThread しても、発火は元のスレッドのままになる。
    """

    detected = Signal(object)  # MediaCandidate

    def __init__(self, watcher, interval_ms: int):
        super().__init__()
        self._watcher = watcher
        self._interval_ms = interval_ms
        self._timer: QTimer | None = None

    @Slot()
    def start(self) -> None:
        """スレッド開始時に呼ばれる。"""
        self._timer = QTimer()
        self._timer.setInterval(self._interval_ms)
        self._timer.timeout.connect(self.poll)
        # 起動時に挿さっているカードでいきなり開くと驚くので、
        # いまの状態を「見たこと」にしてから待ち受ける
        self._watcher.poll()
        self._timer.start()

    @Slot()
    def poll(self) -> None:
        for candidate in self._watcher.poll():
            self.detected.emit(candidate)

    @Slot(bool)
    def set_enabled(self, enabled: bool) -> None:
        if self._timer is None:
            return
        if enabled:
            # 止めている間に挿された分でいきなり開かないようにする
            self._watcher.poll()
            self._timer.start()
        else:
            self._timer.stop()

    @Slot()
    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()


class ImportWorker(QObject):
    """実際にコピーしてカタログへ登録する。"""

    progress = Signal(int, int, str)  # 現在, 全体, 表示名
    finished = Signal(object)  # ImportResult
    failed = Signal(str)

    def __init__(self, import_plan: ImportPlan, selected, catalog_path: Path):
        super().__init__()
        self._plan = import_plan
        self._selected = list(selected)
        self._catalog_path = catalog_path
        self._cancel = False

    @Slot()
    def cancel(self) -> None:
        """中断を要求する。**カットの区切りまで実際には止まらない**。

        コピー途中のファイルを残さないため、1カットの処理には割り込まない。
        """
        self._cancel = True

    @Slot()
    def run(self) -> None:
        try:
            with Catalog(self._catalog_path) as catalog:
                def report(index: int, total: int, planned_shot) -> None:
                    self.progress.emit(index, total, planned_shot.basename)

                result = execute(
                    self._plan,
                    catalog,
                    self._selected,
                    report,
                    should_cancel=lambda: self._cancel,
                )
            self.finished.emit(result)
        except Exception as e:
            self.failed.emit(f"取り込みに失敗しました: {e}")
