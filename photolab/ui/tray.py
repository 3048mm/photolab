"""タスクトレイ常駐。カードを挿すと本体を開く。

**常駐は「検出して知らせる」だけ。写真を勝手にコピーしない**（計画書 §2.2）。
取り込みは必ず人が本体で確認してから行う。

本体ウィンドウは同じプロセスで持つ。別プロセスにすると起動の重複管理や
プロセス間通信が要るが、得るものが無い。ウィンドウを閉じてもトレイに残るよう、
`setQuitOnLastWindowClosed(False)` を呼ぶこと（`ui/app.py` の `run_tray`）。
"""

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from photolab.core.config import Config, default_config_path, save_config
from photolab.core.watcher import MediaWatcher
from photolab.ui import theme
from photolab.ui.main_window import MainWindow
from photolab.ui.workers import WatchWorker

# ポーリング間隔。ドライブレターの列挙だけなので負荷は小さい（計画書 §4-Q3）
POLL_INTERVAL_MS = 2000


class TrayApp(QObject):
    """トレイに常駐して媒体を待つ。"""

    # 別スレッドのワーカーへ渡すのでシグナル経由にする（直接呼ばない）
    _enable_requested = Signal(bool)

    def __init__(
        self,
        config: Config,
        config_path: Path | None = None,
        catalog_path: Path | None = None,
        watcher: MediaWatcher | None = None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._config = config
        self._config_path = config_path or default_config_path()
        self._catalog_path = catalog_path
        self._watcher = watcher or MediaWatcher()
        self._window: MainWindow | None = None

        self._tray = QSystemTrayIcon(theme.app_icon(), self)
        self._tray.setToolTip("Photolab — カードの挿入を待っています")
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.messageClicked.connect(self._on_message_clicked)
        self._tray.setContextMenu(self._build_menu())

        # 検出は専用スレッドで行う。GUI スレッドでファイルシステムに触ると、
        # 応答しないカードがあったときに UI ごと固まる（計画書 §7）
        self._thread = QThread(self)
        self._worker = WatchWorker(self._watcher, POLL_INTERVAL_MS)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.start)
        self._worker.detected.connect(self._on_detected)
        self._enable_requested.connect(self._worker.set_enabled)

    # --- 組み立て ---------------------------------------------------------

    def _build_menu(self) -> QMenu:
        menu = QMenu()

        open_action = menu.addAction("Photolab を開く")
        open_action.triggered.connect(lambda: self.open_window())

        menu.addSeparator()

        self._auto_action = QAction("自動検出", menu)
        self._auto_action.setCheckable(True)
        self._auto_action.setChecked(self._config.watch_auto_detect)
        self._auto_action.toggled.connect(self._on_auto_detect_toggled)
        menu.addAction(self._auto_action)

        self._open_action = QAction("検出したらすぐ開く", menu)
        self._open_action.setCheckable(True)
        self._open_action.setChecked(self._config.watch_open_window)
        self._open_action.setToolTip("オフにすると通知だけ出します")
        self._open_action.toggled.connect(self._on_open_window_toggled)
        menu.addAction(self._open_action)

        menu.addSeparator()
        menu.addAction("終了").triggered.connect(self.quit)
        return menu

    # --- 常駐 -------------------------------------------------------------

    def start(self) -> None:
        self._tray.show()
        # ワーカーは start() の中で「現状を見たこと」にしてから待ち受ける
        self._thread.start()
        if not self._config.watch_auto_detect:
            self._enable_requested.emit(False)

    @Slot(object)
    def _on_detected(self, candidate) -> None:
        """ワーカーからの検出通知。**GUI スレッドで受ける。**"""
        if self._config.watch_open_window:
            self.open_window()
        else:
            self._tray.showMessage(
                "カードを検出しました",
                f"{candidate.display_name}\nクリックすると Photolab を開きます",
                theme.app_icon(),
            )

    # --- 本体ウィンドウ ---------------------------------------------------

    def open_window(self) -> None:
        """本体を開く。既に開いていれば前面に出すだけ（増やさない）。"""
        if self._window is None:
            self._window = MainWindow(
                catalog_path=self._catalog_path, config_path=self._config_path
            )
            self._window.destroyed.connect(self._on_window_destroyed)
        else:
            # 開いたままなら、挿されたカードを拾い直させる
            self._window.refresh_media()

        self._window.show()
        self._window.setWindowState(
            self._window.windowState() & ~self._window.windowState().WindowMinimized
        )
        self._window.raise_()
        self._window.activateWindow()

    @Slot()
    def _on_window_destroyed(self) -> None:
        self._window = None

    # --- 操作 -------------------------------------------------------------

    @Slot()
    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.open_window()

    @Slot()
    def _on_message_clicked(self) -> None:
        self.open_window()

    def _on_auto_detect_toggled(self, checked: bool) -> None:
        self._config.watch_auto_detect = checked
        save_config(self._config, self._config_path)
        # タイマーはワーカースレッドにあるので、シグナルで依頼する
        self._enable_requested.emit(checked)
        self._tray.setToolTip(
            "Photolab — カードの挿入を待っています"
            if checked
            else "Photolab — 自動検出を止めています"
        )

    def _on_open_window_toggled(self, checked: bool) -> None:
        self._config.watch_open_window = checked
        save_config(self._config, self._config_path)

    @Slot()
    def quit(self) -> None:
        from PySide6.QtWidgets import QApplication

        self._enable_requested.emit(False)
        self._thread.quit()
        self._thread.wait(3000)
        self._tray.hide()
        if self._window is not None:
            self._window.close()
        QApplication.quit()
