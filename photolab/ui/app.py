"""GUI のエントリポイント。

    python -m photolab gui
"""

import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from photolab.ui.main_window import MainWindow

# Windows の既定フォントは日本語が不格好になることがあるため明示する。
# Linux 移管を考えて Noto Sans CJK JP を残す。
_FONT_FAMILIES = ["Yu Gothic UI", "Meiryo UI", "Noto Sans CJK JP", "sans-serif"]


def main(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("Photolab")

    font = QFont()
    font.setFamilies(_FONT_FAMILIES)
    app.setFont(font)

    window = MainWindow()
    window.show()
    return app.exec()
