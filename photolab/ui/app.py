"""GUI のエントリポイント。

    python -m photolab gui
"""

import sys

from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from photolab.ui import theme
from photolab.ui.main_window import MainWindow


def _create_app(argv: list[str] | None) -> QApplication:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("Photolab")
    theme.apply(app)  # 配色・フォント・アイコン
    return app


def main(argv: list[str] | None = None) -> int:
    app = _create_app(argv)
    window = MainWindow()
    window.show()
    return app.exec()


def run_tray(argv: list[str] | None = None) -> int:
    """タスクトレイに常駐してカードの挿入を待つ。

    多重起動していると同じカードで2回開いてしまうので、ロックで防ぐ。
    """
    from photolab.core.config import data_dir, load_config
    from photolab.core.single_instance import SingleInstance
    from photolab.ui.tray import TrayApp

    lock = SingleInstance(data_dir() / "watch.lock")
    if not lock.acquire():
        print(
            f"Photolab は既に常駐しています（PID {lock.running_pid()}）",
            file=sys.stderr,
        )
        return 1

    try:
        app = _create_app(argv)
        if not QSystemTrayIcon.isSystemTrayAvailable():
            print("この環境には通知領域がありません", file=sys.stderr)
            return 1

        # ウィンドウを閉じてもトレイに残す（常駐なので）
        app.setQuitOnLastWindowClosed(False)

        tray = TrayApp(load_config())
        tray.start()
        return app.exec()
    finally:
        lock.release()
