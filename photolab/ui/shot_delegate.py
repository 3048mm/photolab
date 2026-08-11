"""サムネイルグリッドの描画。

**3つの状態が同時に成立しうるので、別々の視覚チャンネルに割り当てる。**
既定の描画（`ForegroundRole` など）ではラベル文字しか変わらず、
セルの視覚的な重みを占めるサムネイル画像に反映されないため自前で描く。

| 状態 | チャンネル | 見せ方 |
| :--- | :--- | :--- |
| 選択中（操作対象） | 外枠 | アクセント色の太い枠 |
| チェック（取り込む） | 明るさ | 未チェックは暗くする + 左上のチェックボックス |
| 取り込み済み | 彩度 | グレースケール（モデル側で変換済み）+「済」バッジ |
| 動画 | 右下バッジ | ▶ と再生時間 |
| EXIF が取れない | 右上バッジ | 黄色い △ |
"""

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPalette, QPen, QPolygon
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionButton

from photolab.ui.shot_model import ShotModel

_ACCENT = QColor("#4a9eff")
_WARNING = QColor("#f2c14e")
_BADGE_BG = QColor(0, 0, 0, 170)
_IMPORTED_BG = QColor(90, 90, 90, 210)

_PADDING = 6
_LABEL_HEIGHT = 20
_CHECKBOX_SIZE = 20
_UNCHECKED_OPACITY = 0.38


def _format_duration(seconds: float | None) -> str:
    if not seconds:
        return ""
    minutes, remainder = divmod(int(round(seconds)), 60)
    return f"{minutes}:{remainder:02d}"


class ShotDelegate(QStyledItemDelegate):
    def __init__(self, icon_size: QSize, parent=None):
        super().__init__(parent)
        self._icon_size = icon_size

    def sizeHint(self, option, index) -> QSize:
        return QSize(
            self._icon_size.width() + _PADDING * 2,
            self._icon_size.height() + _PADDING * 2 + _LABEL_HEIGHT,
        )

    # --- 領域の計算 -------------------------------------------------------

    def _image_rect(self, option) -> QRect:
        return QRect(
            option.rect.left() + _PADDING,
            option.rect.top() + _PADDING,
            self._icon_size.width(),
            self._icon_size.height(),
        )

    def checkbox_rect(self, option) -> QRect:
        image = self._image_rect(option)
        return QRect(image.left() + 4, image.top() + 4, _CHECKBOX_SIZE, _CHECKBOX_SIZE)

    # --- 描画 -------------------------------------------------------------

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        image_rect = self._image_rect(option)
        checked = index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
        selected = bool(option.state & QStyle.StateFlag.State_Selected)

        # 背景（選択中は薄く敷いて枠と合わせる）
        if selected:
            painter.fillRect(option.rect, QColor(_ACCENT.red(), _ACCENT.green(),
                                                 _ACCENT.blue(), 40))

        self._draw_thumbnail(painter, index, image_rect, checked)
        self._draw_badges(painter, index, image_rect)
        self._draw_checkbox(painter, option, checked)

        if selected:
            pen = QPen(_ACCENT, 3)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(option.rect.adjusted(1, 1, -2, -2))

        self._draw_label(painter, option, index, image_rect, checked)
        painter.restore()

    def _draw_thumbnail(self, painter, index, image_rect, checked) -> None:
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if icon is None:
            return
        pixmap = icon.pixmap(self._icon_size)
        if pixmap.isNull():
            return

        scaled = pixmap.scaled(
            self._icon_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        target = QRect(0, 0, scaled.width(), scaled.height())
        target.moveCenter(image_rect.center())

        # 未チェックは暗くする（チェック状態を明るさで表す）
        painter.setOpacity(1.0 if checked else _UNCHECKED_OPACITY)
        painter.drawPixmap(target, scaled)
        painter.setOpacity(1.0)

    def _draw_badges(self, painter, index, image_rect) -> None:
        # 取り込み済み: 左下に「済」
        if index.data(ShotModel.IsImportedRole):
            self._draw_pill(
                painter,
                "済",
                QPoint(image_rect.left() + 4, image_rect.bottom() - 4),
                _IMPORTED_BG,
                align_left=True,
            )

        # 動画: 右下に ▶ と再生時間
        if index.data(ShotModel.IsVideoRole):
            duration = _format_duration(index.data(ShotModel.DurationRole))
            self._draw_pill(
                painter,
                f"▶ {duration}" if duration else "▶",
                QPoint(image_rect.right() - 4, image_rect.bottom() - 4),
                _BADGE_BG,
                align_left=False,
            )

        # EXIF が取れない: 右上に黄色い △
        if index.data(ShotModel.WarningRole):
            self._draw_warning(painter, QPoint(image_rect.right() - 6, image_rect.top() + 6))

    def _draw_pill(self, painter, text, anchor, background, align_left) -> None:
        font = QFont(painter.font())
        font.setPointSizeF(max(7.5, font.pointSizeF() - 1))
        painter.setFont(font)

        width = painter.fontMetrics().horizontalAdvance(text) + 12
        height = painter.fontMetrics().height() + 2
        left = anchor.x() if align_left else anchor.x() - width
        rect = QRect(left, anchor.y() - height, width, height)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(background)
        painter.drawRoundedRect(rect, 3, 3)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_warning(self, painter, top_right) -> None:
        size = 20
        left = top_right.x() - size
        top = top_right.y()
        triangle = QPolygon(
            [
                QPoint(left + size // 2, top),
                QPoint(left, top + size),
                QPoint(left + size, top + size),
            ]
        )
        painter.setPen(QPen(QColor("#7a5c00"), 1))
        painter.setBrush(_WARNING)
        painter.drawPolygon(triangle)

        font = QFont(painter.font())
        font.setBold(True)
        font.setPointSizeF(max(7.0, font.pointSizeF() - 1.5))
        painter.setFont(font)
        painter.setPen(QColor("#3a2c00"))
        painter.drawText(
            QRect(left, top + 5, size, size - 5),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            "!",
        )

    def _draw_checkbox(self, painter, option, checked) -> None:
        rect = self.checkbox_rect(option)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 120))
        painter.drawRoundedRect(rect.adjusted(-2, -2, 2, 2), 3, 3)

        button = QStyleOptionButton()
        button.rect = rect
        button.state = QStyle.StateFlag.State_Enabled | (
            QStyle.StateFlag.State_On if checked else QStyle.StateFlag.State_Off
        )
        QStyle.drawPrimitive(
            option.widget.style(),
            QStyle.PrimitiveElement.PE_IndicatorCheckBox,
            button,
            painter,
            option.widget,
        )

    def _draw_label(self, painter, option, index, image_rect, checked) -> None:
        """ファイル名。**色はパレットから取る**（ライト/ダークの両方で読めるように）。"""
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        rect = QRect(
            option.rect.left() + 2,
            image_rect.bottom() + 3,
            option.rect.width() - 4,
            _LABEL_HEIGHT,
        )

        painter.setFont(option.font)
        group = (
            QPalette.ColorGroup.Normal if checked else QPalette.ColorGroup.Disabled
        )
        painter.setPen(option.palette.color(group, QPalette.ColorRole.Text))

        elided = painter.fontMetrics().elidedText(
            text, Qt.TextElideMode.ElideMiddle, rect.width()
        )
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, elided)

    # --- 入力 -------------------------------------------------------------

    def editorEvent(self, event, model, option, index) -> bool:
        """チェックボックスのクリックを拾う。

        自前で描いている以上、既定のチェック操作は効かないので明示的に処理する。
        `ShotModel.setData` 側で「選択中すべてに適用」まで面倒を見ている。
        """
        if (
            event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
            and self.checkbox_rect(option).contains(event.position().toPoint())
        ):
            current = index.data(Qt.ItemDataRole.CheckStateRole)
            new_state = (
                Qt.CheckState.Unchecked
                if current == Qt.CheckState.Checked
                else Qt.CheckState.Checked
            )
            model.setData(index, new_state.value, Qt.ItemDataRole.CheckStateRole)
            return True
        return False
