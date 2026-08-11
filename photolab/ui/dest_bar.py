"""出力先の親フォルダを登録して1クリックで切り替えるバー（計画書 §3.6 ④）。

**フォルダ参照ダイアログを既定の動線にしない。** 毎回、関係ないフォルダの中から
目的地を探すことになり手間がかかる。`[ + ]` を押したときだけダイアログを出す。
"""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QWidget,
)

from photolab.core.config import Config, DestRoot, save_config, suggest_label


class DestRootBar(QWidget):
    """登録済みの親フォルダをボタンで並べる。"""

    changed = Signal(str)  # 選択された親フォルダのフルパス

    def __init__(self, config: Config, config_path: Path, parent=None):
        super().__init__(parent)
        self._config = config
        self._config_path = config_path
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

        self._add_button = QPushButton("＋")
        self._add_button.setToolTip("出力先の親フォルダを登録する")
        self._add_button.setFixedWidth(36)
        self._add_button.clicked.connect(self._on_add)

        # 選択中の親がどこを指しているか常に見えるようにする
        self._path_label = QLabel()
        self._path_label.setStyleSheet("color: #888;")
        self._path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

        self._rebuild()

    # --- 状態 -------------------------------------------------------------

    def current_path(self) -> str | None:
        button = self._group.checkedButton()
        return button.property("dest_path") if button else None

    def _rebuild(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        for button in self._group.buttons():
            self._group.removeButton(button)

        for dest_root in self._config.dest_roots:
            button = QPushButton(dest_root.label)
            button.setCheckable(True)
            button.setProperty("dest_path", dest_root.path)
            button.setToolTip(dest_root.path)
            button.clicked.connect(self._on_select)
            self._group.addButton(button)
            self._layout.addWidget(button)

        self._layout.addWidget(self._add_button)
        self._layout.addSpacing(8)
        self._layout.addWidget(self._path_label, stretch=1)

        self._restore_selection()

    def _restore_selection(self) -> None:
        target = self._config.last_dest_root
        for button in self._group.buttons():
            if button.property("dest_path") == target:
                button.setChecked(True)
                self._on_select()
                return
        if self._group.buttons():
            self._group.buttons()[0].setChecked(True)
            self._on_select()
        else:
            self._path_label.setText("出力先の親フォルダを ＋ で登録してください")

    def select_matching(self, media_label: str) -> bool:
        """媒体のラベル（例: 'NIKON Z 6'）に一致する登録があれば選ぶ。"""
        normalized = media_label.replace(" ", "").upper()
        for button in self._group.buttons():
            if button.text().replace(" ", "").upper() in normalized:
                button.setChecked(True)
                self._on_select()
                return True
        return False

    # --- 操作 -------------------------------------------------------------

    def _on_select(self) -> None:
        path = self.current_path()
        if not path:
            return
        self._path_label.setText(path)
        self._config.last_dest_root = path
        self._save()
        self.changed.emit(path)

    def _on_add(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, "出力先の親フォルダを選ぶ", self.current_path() or ""
        )
        if not selected:
            return
        path = str(Path(selected))
        if any(d.path == path for d in self._config.dest_roots):
            QMessageBox.information(self, "登録済み", "そのフォルダは既に登録されています。")
            return

        label = suggest_label(path, self._config.dest_roots)
        self._config.dest_roots.append(DestRoot(label=label, path=path))
        self._config.last_dest_root = path
        self._save()
        self._rebuild()

    def _on_context_menu(self, point) -> None:
        button = self.childAt(point)
        path = button.property("dest_path") if button else None
        if not path:
            return

        menu = QMenu(self)
        rename = menu.addAction("名前を変更...")
        remove = menu.addAction("登録から削除")
        chosen = menu.exec(self.mapToGlobal(point))

        if chosen == rename:
            self._rename(path, button.text())
        elif chosen == remove:
            self._remove(path)

    def _rename(self, path: str, current: str) -> None:
        new_label, ok = QInputDialog.getText(self, "名前を変更", "表示名:", text=current)
        if not ok or not new_label.strip():
            return
        self._config.dest_roots = [
            DestRoot(label=new_label.strip(), path=d.path) if d.path == path else d
            for d in self._config.dest_roots
        ]
        self._save()
        self._rebuild()

    def _remove(self, path: str) -> None:
        # 登録を消すだけ。実フォルダには触らない
        answer = QMessageBox.question(
            self,
            "登録から削除",
            f"次の登録を削除します。\n\n{path}\n\n"
            "※ 登録が消えるだけで、フォルダとその中身は削除されません。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._config.dest_roots = [d for d in self._config.dest_roots if d.path != path]
        if self._config.last_dest_root == path:
            self._config.last_dest_root = None
        self._save()
        self._rebuild()

    def _save(self) -> None:
        save_config(self._config, self._config_path)
