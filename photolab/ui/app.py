"""GUI のエントリポイント。

    python -m photolab gui
"""

import sys

from PySide6.QtWidgets import QApplication

from photolab.ui import theme
from photolab.ui.main_window import MainWindow


def main(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("Photolab")
    theme.apply(app)  # 配色・フォント・アイコン

    window = MainWindow()
    window.show()
    return app.exec()
