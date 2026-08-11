"""サムネイルグリッドのモデル。

`ImportPlan` を包み、カットごとの「取り込む/取り込まない」チェックを持つ。

**チェック（取り込む対象）と Qt の選択（操作対象）は別物**（計画書 §3.6）。
1枚クリックして確認しただけでチェックが消えてはならない。
"""

from PySide6.QtCore import QAbstractListModel, QModelIndex, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap

from photolab.core.importer import ImportPlan, PlannedShot

# サムネイルがまだ無いセルの見た目
_PLACEHOLDER_SIZE = QSize(192, 128)


def _placeholder(color: str) -> QIcon:
    """サムネイルが無いセルに出す単色の矩形。"""
    pixmap = QPixmap(_PLACEHOLDER_SIZE)
    pixmap.fill(QColor(color))
    return QIcon(pixmap)


def _to_grayscale(icon: QIcon) -> QIcon:
    """取り込み済みを示すためのグレースケール版を作る。"""
    pixmap = icon.pixmap(_PLACEHOLDER_SIZE * 4)  # 元の解像度を保って取り出す
    if pixmap.isNull():
        return icon
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_Grayscale8)
    return QIcon(QPixmap.fromImage(image))


class ShotModel(QAbstractListModel):
    """1 行 = 1 カット。"""

    # デリゲートが描画に使うロール。判定はモデルが持ち、デリゲートは描くだけにする
    ShotRole = int(Qt.ItemDataRole.UserRole) + 1
    IsVideoRole = int(Qt.ItemDataRole.UserRole) + 2
    IsImportedRole = int(Qt.ItemDataRole.UserRole) + 3
    IsFallbackRole = int(Qt.ItemDataRole.UserRole) + 4
    DurationRole = int(Qt.ItemDataRole.UserRole) + 5
    WarningRole = int(Qt.ItemDataRole.UserRole) + 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self._plan: ImportPlan | None = None
        self._shots: list[PlannedShot] = []
        self._checked: list[bool] = []
        self._icons: dict[int, QIcon] = {}
        self._selection_provider = None
        self._pending = _placeholder("#3a3a3a")
        self._video = _placeholder("#2b3a4a")
        self._broken = _placeholder("#4a2b2b")

    # --- データの差し替え ------------------------------------------------

    def set_plan(self, plan: ImportPlan, keep_state: bool = False) -> None:
        """新しい取り込み計画を表示する。既定のチェックは未取り込みのみ。

        `keep_state` は「同じカット群で出力先だけ変わった」場合に使う。
        チェックとサムネイルを引き継ぐ（並び順は `build_plan` が保つ）。
        """
        previous_checked = list(self._checked)
        previous_icons = dict(self._icons)

        self.beginResetModel()
        self._plan = plan
        self._shots = list(plan.shots)
        if keep_state and len(previous_checked) == len(self._shots):
            self._checked = previous_checked
            self._icons = previous_icons
        else:
            self._checked = [not s.already_imported for s in self._shots]
            self._icons = {}
        self.endResetModel()

    def set_plan_empty(self) -> None:
        """媒体が無いときなど、グリッドを空にする。"""
        self.beginResetModel()
        self._plan = None
        self._shots = []
        self._checked = []
        self._icons.clear()
        self.endResetModel()

    def plan(self) -> ImportPlan | None:
        return self._plan

    def shot_at(self, row: int) -> PlannedShot:
        return self._shots[row]

    def set_icon(self, row: int, icon: QIcon | None) -> None:
        """サムネイルができたセルだけを再描画する。

        取り込み済みのカットは**ここでグレースケール化しておく**。
        描画のたびに変換すると 355 セルのスクロールが重くなるため。
        """
        if not 0 <= row < len(self._shots):
            return
        if icon is None:
            self._icons[row] = self._broken
        elif self._shots[row].already_imported:
            self._icons[row] = _to_grayscale(icon)
        else:
            self._icons[row] = icon
        index = self.index(row, 0)
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.DecorationRole])

    # --- QAbstractListModel ---------------------------------------------

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._shots)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        shot = self._shots[row]

        if role == Qt.ItemDataRole.DisplayRole:
            return shot.basename

        if role == Qt.ItemDataRole.DecorationRole:
            # ここでサムネイルを生成してはならない（スクロールが固まる）
            if row in self._icons:
                return self._icons[row]
            return self._video if shot.shot.is_video else self._pending

        if role == Qt.ItemDataRole.CheckStateRole:
            return (
                Qt.CheckState.Checked if self._checked[row] else Qt.CheckState.Unchecked
            )

        if role == self.IsVideoRole:
            return shot.shot.is_video

        if role == self.IsImportedRole:
            return shot.already_imported

        if role == self.IsFallbackRole:
            return shot.dedup_key.is_fallback

        if role == self.DurationRole:
            return shot.shot.duration_seconds

        if role == self.WarningRole:
            return self._warning_text(shot)

        if role == Qt.ItemDataRole.ToolTipRole:
            lines = [
                f"元ファイル: {shot.shot.source_name}",
                f"取り込み先: {', '.join(f.dest.name for f in shot.files)}",
            ]
            if shot.already_imported:
                lines.append("★ 取り込み済み")
            warning = self._warning_text(shot)
            if warning:
                lines.append(f"⚠ {warning}")
            return "\n".join(lines)

        if role == self.ShotRole:
            return shot
        return None

    @staticmethod
    def _warning_text(shot: PlannedShot) -> str:
        """黄色い △ に添える理由。無ければ空文字。"""
        if shot.shot.captured_at is None:
            return (
                "撮影日時を取得できませんでした。"
                "リネームせず元のファイル名のまま取り込みます"
            )
        if shot.dedup_key.is_fallback:
            return (
                "シリアル番号とショットカウントを取得できませんでした。"
                "撮影日時とファイル名で重複を判定します（誤判定の可能性があります）"
            )
        return ""

    def set_selection_provider(self, provider) -> None:
        """「いま選択されている行」を返す関数を受け取る。

        チェックボックスのクリックを**選択中すべてに適用**するために使う
        （計画書 §3.6）。モデルが View の選択状態を直接見に行かずに済ませる。
        """
        self._selection_provider = provider

    def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid() or role != Qt.ItemDataRole.CheckStateRole:
            return False

        checked = Qt.CheckState(value) == Qt.CheckState.Checked
        row = index.row()

        # クリックした行が選択に含まれていれば、選択中すべてに同じ操作をする
        selected = self._selection_provider() if self._selection_provider else []
        rows = list(selected) if row in selected else [row]

        self.set_checked_rows(rows, checked)
        return True

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        # 取り込み済みでも選択・チェックはできる（再取り込みを許す / Q3 合意）
        return (
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsUserCheckable
        )

    # --- チェックの一括操作 ----------------------------------------------

    def set_checked_rows(self, rows, checked: bool) -> None:
        rows = [r for r in rows if 0 <= r < len(self._checked)]
        if not rows:
            return
        for row in rows:
            self._checked[row] = checked
        self.dataChanged.emit(
            self.index(min(rows), 0),
            self.index(max(rows), 0),
            [Qt.ItemDataRole.CheckStateRole],
        )

    def toggle_rows(self, rows) -> None:
        """選択中のチェックを反転する。1つでも未チェックがあれば全部チェックする。"""
        rows = [r for r in rows if 0 <= r < len(self._checked)]
        if not rows:
            return
        self.set_checked_rows(rows, not all(self._checked[r] for r in rows))

    def check_all(self, checked: bool) -> None:
        self.set_checked_rows(range(len(self._checked)), checked)

    def check_new_only(self) -> None:
        """未取り込みだけをチェックする（起動時の既定状態）。"""
        for row, shot in enumerate(self._shots):
            self._checked[row] = not shot.already_imported
        if self._shots:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._shots) - 1, 0),
                [Qt.ItemDataRole.CheckStateRole],
            )

    def checked_rows(self) -> list[int]:
        """チェック済みの行番号。計画を作り直したときの対応付けに使う。"""
        return [row for row, on in enumerate(self._checked) if on]

    def checked_shots(self) -> list[PlannedShot]:
        return [s for s, on in zip(self._shots, self._checked) if on]

    def checked_count(self) -> int:
        return sum(self._checked)
