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
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPalette, QPen, QPolygon
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from photolab.ui import theme
from photolab.ui.shot_model import ShotModel

_PADDING = 10  # タイル内の余白。アイテム間の隙間は 0 なのでここで間を作る
_LABEL_HEIGHT = 20
_CHECKBOX_SIZE = 20
_UNCHECKED_OPACITY = 0.38
_CORNER = 0  # 写真の角は落とさない（格子の直線と揃える）


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

        # タイルの下地。隙間なく敷き詰め、区切り線が隣り合って格子になる
        painter.fillRect(
            option.rect, theme.TILE_SELECTED if selected else theme.GRID_BASE
        )
        painter.setPen(QPen(theme.TILE_BORDER, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(option.rect.adjusted(0, 0, -1, -1))

        self._draw_thumbnail(painter, index, image_rect, checked)
        self._draw_badges(painter, index, image_rect)
        self._draw_checkbox(painter, option, checked)

        if selected:
            painter.setPen(QPen(theme.selection_border(option.palette), 2))
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
        painter.drawPixmap(target, scaled)
        if not checked:
            # 暗幕をかぶせる（不透明度を下げると明るいタイルの上では白く飛ぶ）
            painter.fillRect(target, theme.UNCHECKED_VEIL)

        # 写真をタイルの下地から浮かせる細い明るい縁
        painter.setPen(QPen(theme.THUMB_BORDER, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(target.adjusted(0, 0, -1, -1))

    def _draw_badges(self, painter, index, image_rect) -> None:
        # 取り込み済み: 左下にチェックマークのバッジ
        if index.data(ShotModel.IsImportedRole):
            self._draw_imported_badge(
                painter, QPoint(image_rect.left() + 5, image_rect.bottom() - 5)
            )

        # 静止画: 右下に構成（RAW+JPG / RAW / JPG）。
        # 現像の元があるか、ペアなのかを一目で分かるようにする
        composition = index.data(ShotModel.CompositionRole)
        if composition:
            self._draw_pill(
                painter,
                composition,
                QPoint(image_rect.right() - 5, image_rect.bottom() - 5),
                theme.JPEG_ONLY_BG
                if index.data(ShotModel.IsJpegOnlyRole)
                else theme.BADGE_BG,
                align_left=False,
            )

        # 動画: 右下に ▶ と再生時間
        if index.data(ShotModel.IsVideoRole):
            duration = _format_duration(index.data(ShotModel.DurationRole))
            self._draw_pill(
                painter,
                duration,
                QPoint(image_rect.right() - 5, image_rect.bottom() - 5),
                theme.BADGE_BG,
                align_left=False,
                glyph=True,
            )

        # EXIF が取れない: 右上に黄色い △
        if index.data(ShotModel.WarningRole):
            self._draw_warning(painter, QPoint(image_rect.right() - 6, image_rect.top() + 6))

    def _draw_pill(self, painter, text, anchor, background, align_left, glyph=False) -> None:
        """角丸のバッジ。`glyph=True` なら先頭に再生マークを描く。

        再生マークは文字（▶）ではなく多角形で描く。フォントに字形が無い環境で
        豆腐になるのを避けるため。
        """
        font = QFont(painter.font())
        font.setPointSizeF(max(7.5, font.pointSizeF() - 0.5))
        painter.setFont(font)

        metrics = painter.fontMetrics()
        height = metrics.height() + 4
        glyph_size = int(height * 0.42)
        glyph_space = glyph_size + 5 if glyph else 0
        width = metrics.horizontalAdvance(text) + 14 + glyph_space
        left = anchor.x() if align_left else anchor.x() - width
        rect = QRect(left, anchor.y() - height, width, height)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(background)
        painter.drawRoundedRect(rect, height // 2, height // 2)

        painter.setPen(theme.BADGE_INK)
        text_rect = rect.adjusted(7 + glyph_space, 0, -7, 0)
        if glyph:
            top = rect.center().y() - glyph_size // 2
            painter.setBrush(theme.BADGE_INK)
            painter.drawPolygon(
                QPolygon(
                    [
                        QPoint(rect.left() + 8, top),
                        QPoint(rect.left() + 8, top + glyph_size),
                        QPoint(rect.left() + 8 + int(glyph_size * 0.85), top + glyph_size // 2),
                    ]
                )
            )
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_imported_badge(self, painter, bottom_left) -> None:
        """取り込み済みを示す丸いチェックバッジ。

        文字（「済」）にしない。字形に依存せず、狭い場所でも読めるため。
        """
        size = 20
        rect = QRect(bottom_left.x(), bottom_left.y() - size, size, size)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 70))
        painter.drawEllipse(rect.adjusted(0, 1, 0, 2))
        painter.setBrush(theme.IMPORTED_BG)
        painter.drawEllipse(rect)

        pen = QPen(theme.IMPORTED_INK, 2.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolyline(
            QPolygon(
                [
                    QPoint(rect.left() + 5, rect.center().y()),
                    QPoint(rect.center().x() - 1, rect.bottom() - 6),
                    QPoint(rect.right() - 4, rect.top() + 6),
                ]
            )
        )

    def _draw_warning(self, painter, top_right) -> None:
        """角を丸めた黄色い警告三角。"""
        size = 21
        left = top_right.x() - size
        top = top_right.y()

        path = QPainterPath()
        path.moveTo(left + size / 2, top)
        path.lineTo(left + size, top + size * 0.9)
        path.lineTo(left, top + size * 0.9)
        path.closeSubpath()

        painter.setPen(QPen(QColor(0, 0, 0, 60), 1))
        painter.setBrush(theme.WARNING)
        painter.drawPath(path)

        font = QFont(painter.font())
        font.setBold(True)
        font.setPointSizeF(max(7.0, font.pointSizeF() - 1.0))
        painter.setFont(font)
        painter.setPen(theme.WARNING_INK)
        painter.drawText(
            QRect(left, top + int(size * 0.28), size, size),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            "!",
        )

    def _draw_checkbox(self, painter, option, checked) -> None:
        """チェックボックスは自前で描く。

        OS 標準の未チェック表示は白地に薄い枠で、明るい写真の上では消えてしまう。
        写真の上に置く前提で、影と塗りを自分で決める。
        """
        rect = self.checkbox_rect(option)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 70))
        painter.drawRoundedRect(rect.adjusted(0, 1, 0, 2), 5, 5)

        if checked:
            painter.setBrush(theme.selection_border(option.palette))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect, 5, 5)

            pen = QPen(QColor(255, 255, 255), 2.2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawPolyline(
                QPolygon(
                    [
                        QPoint(rect.left() + 5, rect.center().y()),
                        QPoint(rect.center().x() - 1, rect.bottom() - 6),
                        QPoint(rect.right() - 4, rect.top() + 6),
                    ]
                )
            )
        else:
            painter.setBrush(QColor(255, 255, 255, 235))
            painter.setPen(QPen(QColor(0, 0, 0, 110), 1))
            painter.drawRoundedRect(rect, 5, 5)

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
