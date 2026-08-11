"""メインウィンドウ。レイアウトの組み立てとシグナルの配線だけを行う。

判断が要る処理は `photolab/core/` に置く（`.claude/skills/photolab-gui/SKILL.md` §1）。
画面構成は計画書 §3.6。
"""

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QFont, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGraphicsOpacityEffect,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from photolab.core.catalog import Catalog
from photolab.core.config import (
    default_catalog_path,
    default_config_path,
    load_config,
    save_config,
)
from photolab.core.developer import (
    DeveloperNotFoundError,
    find_darktable,
    folder_has_raw,
    jpeg_only_names,
    launch,
)
from photolab.core.importer import build_plan
from photolab.core.maintenance import check_catalog, remove_missing
from photolab.core.naming import strip_date_prefix, suggest_folder_name
from photolab.core.scanner import MediaCandidate, find_media
from photolab.ui import theme
from photolab.ui.dest_bar import DestRootBar
from photolab.ui.shot_delegate import ShotDelegate
from photolab.ui.shot_model import ShotModel
from photolab.ui.workers import ImportWorker, PlanWorker, ThumbnailWorker

_ICON_SIZE = QSize(192, 128)


def _separator() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    return line


class MainWindow(QMainWindow):
    """1 ウィンドウで上から下へ進む構成（ウィザードにしない）。"""

    _thumbnails_stopped = Signal()

    def __init__(self, catalog_path: Path | None = None, config_path: Path | None = None):
        super().__init__()
        self._catalog_path = catalog_path or default_catalog_path()
        self._config_path = config_path or default_config_path()
        self._config = load_config(self._config_path)

        # 強制終了で running のまま残ったバッチを片付ける
        with Catalog(self._catalog_path) as catalog:
            catalog.abort_stale_batches()

        self._media: list[MediaCandidate] = []
        # (スレッド, ワーカー) の組。ワーカーは参照を保持しないと GC される
        self._jobs: list[tuple[QThread, object]] = []
        self._thumbnail_worker: ThumbnailWorker | None = None
        self._import_worker: ImportWorker | None = None
        self._busy = False
        # 出力先の計画を作り直すべきかの判定に使う（出力先 / 日付分割 / 撮影名）
        self._plan_signature: tuple | None = None

        # 出力先の入力中に毎回作り直さないための遅延タイマー
        self._recompute_timer = QTimer(self)
        self._recompute_timer.setSingleShot(True)
        self._recompute_timer.timeout.connect(self._recompute_plan)

        self.setWindowTitle("Photolab")
        self.resize(self._config.window_width, self._config.window_height)
        self._build_menu()
        self._build()
        self.refresh_media()

    # --- 組み立て ---------------------------------------------------------

    def _build_menu(self) -> None:
        tools = self.menuBar().addMenu("ツール")
        action = tools.addAction("カタログを点検...")
        action.setToolTip("取り込み済みの記録と実ファイルの食い違いを調べる")
        action.triggered.connect(self._on_check_catalog)

    def _on_check_catalog(self) -> None:
        """カタログと実ファイルの食い違いを調べ、必要なら記録を消す。

        **写真そのものは削除しない。** 消えるのはカタログの記録だけ。
        """
        with Catalog(self._catalog_path) as catalog:
            report = check_catalog(catalog)

            if report.ok:
                QMessageBox.information(
                    self,
                    "カタログの点検",
                    f"登録 {report.total} 件。問題はありません。",
                )
                return

            listed = "\n".join(
                f"  {r['dest_path']}\\{r['dest_name']}" for r in report.missing[:15]
            )
            more = (
                f"\n  ... 他 {len(report.missing) - 15} 件"
                if len(report.missing) > 15
                else ""
            )
            answer = QMessageBox.question(
                self,
                "カタログの点検",
                f"登録 {report.total} 件のうち、"
                f"{len(report.missing)} 件は実ファイルがありません。\n"
                "取り込んだ後に削除された可能性があります。\n\n"
                f"{listed}{more}\n\n"
                "これらの記録をカタログから削除しますか？\n"
                "・写真そのものは削除しません\n"
                "・該当のカットは次回から『未取り込み』として扱われます",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

            removed = remove_missing(catalog, report)

        QMessageBox.information(
            self,
            "カタログの点検",
            f"{removed} 件の記録を削除しました。\n写真は削除していません。",
        )
        self._start_plan()  # グレーアウトの状態を更新する

    def _build(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.addLayout(self._build_media_row())
        layout.addWidget(self._summary_label())
        layout.addWidget(_separator())

        self._grid_stack = QStackedWidget()
        self._grid_stack.addWidget(self._build_grid())
        self._grid_stack.addWidget(self._build_empty_state())
        layout.addWidget(self._grid_stack, stretch=1)
        layout.addLayout(self._build_selection_row())
        layout.addWidget(_separator())
        layout.addLayout(self._build_dest_rows())
        layout.addWidget(_separator())
        layout.addLayout(self._build_action_row())
        self.setCentralWidget(root)

    def _build_media_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self._media_combo = QComboBox()
        self._media_combo.currentIndexChanged.connect(self._on_media_changed)
        self._rescan_button = QPushButton("再検出")
        self._rescan_button.clicked.connect(self.refresh_media)

        row.addWidget(QLabel("メディア"))
        row.addWidget(self._media_combo, stretch=1)
        row.addWidget(self._rescan_button)
        return row

    def _summary_label(self) -> QLabel:
        self._summary = QLabel("メディアを検出しています...")
        return self._summary

    def _build_empty_state(self) -> QWidget:
        """媒体が無いときなどにグリッドの代わりに出す。"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon = QLabel()
        icon.setPixmap(theme.app_icon().pixmap(QSize(72, 72)))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # 主役ではないので沈ませる
        effect = QGraphicsOpacityEffect(icon)
        effect.setOpacity(0.35)
        icon.setGraphicsEffect(effect)

        self._empty_title = QLabel()
        title_font = QFont()
        title_font.setPointSizeF(title_font.pointSizeF() + 2)
        self._empty_title.setFont(title_font)
        self._empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._empty_hint = QLabel()
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_hint.setStyleSheet(
            f"color: {theme.muted_text(self.palette()).name()};"
        )

        layout.addWidget(icon)
        layout.addSpacing(theme.GAP)
        layout.addWidget(self._empty_title)
        layout.addWidget(self._empty_hint)
        return widget

    def _show_empty(self, title: str, hint: str = "") -> None:
        self._empty_title.setText(title)
        self._empty_hint.setText(hint)
        self._grid_stack.setCurrentIndex(1)

    def _show_grid(self) -> None:
        self._grid_stack.setCurrentIndex(0)

    def _build_grid(self) -> QListView:
        self._model = ShotModel(self)
        self._model.dataChanged.connect(lambda *_: self._update_counts())
        self._model.modelReset.connect(self._update_counts)

        self._view = QListView()
        self._view.setModel(self._model)
        # 状態（選択 / チェック / 取り込み済み / 動画 / 警告）を描き分ける
        self._view.setItemDelegate(ShotDelegate(_ICON_SIZE, self._view))
        self._view.setViewMode(QListView.ViewMode.IconMode)
        self._view.setResizeMode(QListView.ResizeMode.Adjust)
        self._view.setUniformItemSizes(True)  # 全アイテム同サイズ = 描画が速い
        self._view.setIconSize(_ICON_SIZE)
        # タイルを敷き詰めて格子にするため、アイテム間の隙間は空けない
        self._view.setSpacing(0)
        self._view.setMovement(QListView.Movement.Static)
        self._view.setFrameShape(QListView.Shape.NoFrame)
        # 下地はビューポートに設定する。ビュー本体に入れても描画に反映されない
        viewport = self._view.viewport()
        view_palette = viewport.palette()
        view_palette.setColor(viewport.backgroundRole(), theme.GRID_VOID)
        viewport.setPalette(view_palette)
        viewport.setAutoFillBackground(True)
        # Shift / Ctrl での範囲選択は ExtendedSelection の標準動作に任せる
        self._view.setSelectionMode(QListView.SelectionMode.ExtendedSelection)

        # チェックボックスのクリックを選択中すべてに適用するため、
        # モデルに「いま選択されている行」の取得手段を渡す
        self._model.set_selection_provider(self._selected_rows)

        # Space で選択中のチェックを反転
        toggle = QShortcut(QKeySequence(Qt.Key.Key_Space), self._view)
        toggle.activated.connect(self._toggle_selected)
        return self._view

    def _build_selection_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        for text, tooltip, handler in (
            ("すべて選択", "全カットにチェックを付ける", lambda: self._model.check_all(True)),
            ("すべて解除", "全カットのチェックを外す", lambda: self._model.check_all(False)),
            ("未取り込みのみ", "未取り込みだけチェックする", self._model.check_new_only),
            (
                "選択をチェック",
                "選択中のカットにチェックを付ける（Shift クリックで範囲選択）",
                lambda: self._model.set_checked_rows(self._selected_rows(), True),
            ),
            (
                "選択を解除",
                "選択中のカットのチェックを外す",
                lambda: self._model.set_checked_rows(self._selected_rows(), False),
            ),
        ):
            button = QPushButton(text)
            button.setToolTip(tooltip)
            button.clicked.connect(handler)
            row.addWidget(button)

        self._count_label = QLabel()
        row.addStretch(1)
        row.addWidget(self._count_label)
        return row

    def _build_dest_rows(self) -> QVBoxLayout:
        box = QVBoxLayout()

        parent_row = QHBoxLayout()
        self._dest_bar = DestRootBar(self._config, self._config_path)
        self._dest_bar.changed.connect(self._on_dest_parent_changed)
        parent_row.addWidget(QLabel("出力先"))
        parent_row.addWidget(self._dest_bar, stretch=1)

        # 新規フォルダ名の入力と、既存フォルダの選択を1つにまとめる。
        # 既存の撮影フォルダへ追加取り込みする運用が実在するため（architecture.md §4.1）
        name_row = QHBoxLayout()
        self._folder_name = QComboBox()
        self._folder_name.setEditable(True)
        self._folder_name.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._folder_name.lineEdit().setPlaceholderText("20260810 撮影名")
        self._folder_name.setToolTip(
            "新しいフォルダ名を入力するか、既存のフォルダを選びます（既存なら追加取り込み）"
        )
        self._folder_name.currentTextChanged.connect(self._on_folder_name_changed)
        self._name_label = QLabel("フォルダ名")
        name_row.addWidget(self._name_label)
        name_row.addWidget(self._folder_name, stretch=1)

        # 既定はオフ。1枚のカードに複数日が混在していても1フォルダにまとめる運用が
        # 実在するため、自動では分割しない（architecture.md §7）
        self._split_by_date = QCheckBox("日付ごとのフォルダに振り分ける")
        self._split_by_date.setToolTip(
            "撮影日ごとに <親フォルダ>\\YYYYMMDD\\ を作って振り分けます。\n"
            "撮影名を入力すると <YYYYMMDD 撮影名>\\ になります。"
        )
        self._split_by_date.toggled.connect(self._on_split_toggled)
        name_row.addWidget(self._split_by_date)

        self._dest_preview = QLabel()
        self._dest_preview.setStyleSheet("color: #888;")

        box.addLayout(parent_row)
        box.addLayout(name_row)
        box.addWidget(self._dest_preview)
        return box

    def _build_action_row(self) -> QVBoxLayout:
        box = QVBoxLayout()
        self._warning = QLabel()
        self._warning.setStyleSheet("color: #c08000;")

        bar_row = QHBoxLayout()
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress_label = QLabel()
        bar_row.addWidget(self._progress, stretch=1)
        bar_row.addWidget(self._progress_label)

        button_row = QHBoxLayout()
        self._open_developer = QCheckBox("取り込み後に darktable で開く")
        self._open_developer.setChecked(self._config.launch_darktable_after_import)
        self._open_developer.toggled.connect(self._on_open_developer_toggled)
        if find_darktable(self._config.darktable_executable) is None:
            self._open_developer.setEnabled(False)
            self._open_developer.setChecked(False)
            self._open_developer.setToolTip(
                "darktable の実行ファイルが見つかりません。"
                "config.toml の [darktable] executable にパスを指定してください。"
            )
        button_row.addWidget(self._open_developer)

        # RAW+JPEG のペアが両方 darktable に入るのを避ける。
        # darktable 側はフォルダ単位でしか JPEG を無視できないため、
        # 「ペアのときだけ外す」ことはできない（外すと JPEG 単独も落ちる）
        self._develop_jpeg = QCheckBox("JPEG も現像対象にする")
        self._develop_jpeg.setChecked(self._config.develop_jpeg)
        self._develop_jpeg.setToolTip(
            "オフ: フォルダに RAW があれば JPEG を darktable に読み込ませません\n"
            "（RAW が無いフォルダでは、この設定に関わらず JPEG を読み込みます）"
        )
        self._develop_jpeg.toggled.connect(self._on_develop_jpeg_toggled)
        button_row.addWidget(self._develop_jpeg)

        self._import_button = QPushButton("取り込み開始")
        self._import_button.setDefault(True)
        self._import_button.clicked.connect(self._on_import)

        # 取り込み中だけ出す。強制終了させないための逃げ道
        self._cancel_button = QPushButton("中断")
        self._cancel_button.setVisible(False)
        self._cancel_button.clicked.connect(self._on_cancel)

        button_row.addStretch(1)
        button_row.addWidget(self._cancel_button)
        button_row.addWidget(self._import_button)

        box.addWidget(self._warning)
        box.addLayout(bar_row)
        box.addLayout(button_row)
        return box

    # --- 媒体 -------------------------------------------------------------

    def refresh_media(self) -> None:
        self._media = find_media()
        self._media_combo.blockSignals(True)
        self._media_combo.clear()
        for candidate in self._media:
            self._media_combo.addItem(candidate.display_name)
        self._media_combo.blockSignals(False)

        if not self._media:
            self._summary.setText("メディアが見つかりません")
            self._model.set_plan_empty()
            self._warning.clear()  # 前の媒体の警告を残さない
            self._dest_preview.clear()
            self._plan_signature = None
            self._show_empty(
                "カードが見つかりません",
                "SD カードを挿してから［再検出］を押してください",
            )
            return
        self._media_combo.setCurrentIndex(0)
        self._on_media_changed()

    def _current_media(self) -> MediaCandidate | None:
        index = self._media_combo.currentIndex()
        return self._media[index] if 0 <= index < len(self._media) else None

    def _on_media_changed(self) -> None:
        candidate = self._current_media()
        if candidate is None:
            return
        # 媒体のラベル（NIKON Z 6）に一致する親フォルダがあれば自動で選ぶ
        self._dest_bar.select_matching(candidate.label)
        self._start_plan()

    # --- 計画 -------------------------------------------------------------

    def _dest_root(self) -> Path | None:
        """計画に渡す出力先。

        日付分割が有効なときは**親フォルダそのもの**を返す
        （その直下に日付フォルダが作られる / `importer.build_plan`）。
        """
        parent = self._dest_bar.current_path()
        if not parent:
            return None
        if self._split_by_date.isChecked():
            return Path(parent)
        name = self._folder_name.currentText().strip()
        return Path(parent) / name if name else None

    def _date_suffix(self) -> str:
        """日付フォルダに付ける撮影名。入力済みの日付部分は外す。"""
        return strip_date_prefix(self._folder_name.currentText())

    def _on_split_toggled(self, checked: bool) -> None:
        self._name_label.setText("撮影名（任意）" if checked else "フォルダ名")
        self._schedule_recompute()

    def _on_dest_parent_changed(self, _path: str) -> None:
        self._populate_folder_names()
        self._schedule_recompute()

    def _on_folder_name_changed(self, _text: str) -> None:
        self._schedule_recompute()

    def _populate_folder_names(self) -> None:
        """親フォルダ直下の既存フォルダを候補に出す（新しい順）。"""
        parent = self._dest_bar.current_path()
        current = self._folder_name.currentText()

        self._folder_name.blockSignals(True)
        self._folder_name.clear()
        if parent:
            try:
                names = sorted(
                    (
                        p.name
                        for p in Path(parent).iterdir()
                        if p.is_dir() and not p.name.startswith(".")
                    ),
                    reverse=True,
                )
            except OSError:
                names = []
            self._folder_name.addItems(names)
        self._folder_name.setCurrentText(current)
        self._folder_name.blockSignals(False)

    def _schedule_recompute(self) -> None:
        """出力先の変更を少し待ってから計画に反映する（入力中の連打を抑える）。"""
        self._update_dest_preview()
        self._recompute_timer.start(250)

    def _recompute_plan(self) -> None:
        """出力先だけを変えて計画を作り直す。**カードは読み直さない。**

        連番の衝突回避は出力先の既存ファイルに依存するため、
        出力先が変わったら作り直す必要がある。
        """
        self._recompute_timer.stop()
        import_plan = self._model.plan()
        dest = self._dest_root()
        if import_plan is None or dest is None:
            return

        # 出力先そのものが同じでも、日付分割の有無や撮影名で結果は変わる
        signature = (dest, self._split_by_date.isChecked(), self._date_suffix())
        if signature == self._plan_signature:
            return
        self._plan_signature = signature

        shots = [s.shot for s in import_plan.shots]
        # カード I/O を伴わない軽い処理なので GUI スレッドで済ませる
        with Catalog(self._catalog_path) as catalog:
            rebuilt = build_plan(
                shots,
                import_plan.source_root,
                dest,
                catalog,
                split_by_date=self._split_by_date.isChecked(),
                date_suffix=self._date_suffix(),
            )
        self._model.set_plan(rebuilt, keep_state=True)
        self._update_dest_preview()

    def _update_dest_preview(self) -> None:
        dest = self._dest_root()
        if dest is None:
            self._dest_preview.setText("親フォルダとフォルダ名を指定してください")
            return

        import_plan = self._model.plan()
        if self._split_by_date.isChecked() and import_plan is not None:
            dirs = import_plan.dest_dirs
            shown = "、".join(d.name for d in dirs[:4])
            more = f" ほか{len(dirs) - 4}件" if len(dirs) > 4 else ""
            self._dest_preview.setText(
                f"→ {dest}\\ の下に {len(dirs)} 個のフォルダ: {shown}{more}"
            )
            return

        state = "既存フォルダにマージ" if dest.is_dir() else "新規作成"
        self._dest_preview.setText(f"→ {dest}\\　({state})")

    def _start_plan(self) -> None:
        candidate = self._current_media()
        if candidate is None or self._busy:
            return
        self._stop_thumbnails()
        self._set_busy(True)
        self._summary.setText("メディアを読み取っています...")
        self._show_empty("読み取り中...", f"{candidate.display_name} を走査しています")

        dest = self._dest_root() or Path(self._dest_bar.current_path() or ".")
        worker = PlanWorker(candidate.root, dest, self._catalog_path)
        worker.finished.connect(self._on_plan_ready)
        worker.failed.connect(self._on_failed)
        self._run(worker)

    def _on_plan_ready(self, import_plan) -> None:
        self._set_busy(False)
        self._model.set_plan(import_plan)
        self._populate_folder_names()

        if import_plan.shots:
            self._show_grid()
        else:
            self._show_empty(
                "取り込めるファイルがありません",
                "このカードの DCIM フォルダに対応形式のファイルが見つかりませんでした",
            )

        if not self._folder_name.currentText().strip():
            self._folder_name.setCurrentText(
                suggest_folder_name([s.shot for s in import_plan.shots])
            )

        self._summary.setText(
            f"{len(import_plan.shots)} カット / "
            f"未取り込み {len(import_plan.new_shots)} / "
            f"取り込み済み {len(import_plan.skipped)}"
        )
        warnings = len(import_plan.warnings)
        self._warning.setText(
            f"⚠ {warnings} カットが弱いキーで判定されています"
            "（シリアル+ショットカウントを取得できませんでした）"
            if warnings
            else ""
        )
        self._update_dest_preview()
        self._start_thumbnails(import_plan)

    # --- サムネイル -------------------------------------------------------

    def _start_thumbnails(self, import_plan) -> None:
        paths = [s.primary.source for s in import_plan.shots]
        if not paths:
            return
        worker = ThumbnailWorker(paths)
        worker.ready.connect(self._on_thumbnail_ready)
        self._thumbnail_worker = worker
        self._thumbnails_stopped.connect(worker.stop, Qt.ConnectionType.DirectConnection)
        self._run(worker)

    def _on_thumbnail_ready(self, row: int, data) -> None:
        if data is None:
            self._model.set_icon(row, None)
            return
        pixmap = QPixmap()
        pixmap.loadFromData(data)
        self._model.set_icon(row, QIcon(pixmap) if not pixmap.isNull() else None)

    def _stop_thumbnails(self) -> None:
        if self._thumbnail_worker is not None:
            self._thumbnails_stopped.emit()
            self._thumbnail_worker = None

    # --- 選択 -------------------------------------------------------------

    def _selected_rows(self) -> list[int]:
        return [i.row() for i in self._view.selectionModel().selectedIndexes()]

    def _toggle_selected(self) -> None:
        self._model.toggle_rows(self._selected_rows())

    def _update_counts(self) -> None:
        count = self._model.checked_count()
        self._count_label.setText(f"取り込む {count} カット")
        # 対象が無いときに押せてしまうと、押してから断られることになる
        if not self._busy:
            self._import_button.setEnabled(count > 0)

    # --- 実行 -------------------------------------------------------------

    def _on_import(self) -> None:
        dest = self._dest_root()
        if dest is None:
            QMessageBox.warning(self, "取り込み", "親フォルダとフォルダ名を指定してください。")
            return

        # 入力直後で遅延タイマーが未発火の場合に備え、ここで確実に確定させる
        self._recompute_plan()

        import_plan = self._model.plan()
        checked = self._model.checked_shots()
        if import_plan is None or not checked:
            QMessageBox.information(self, "取り込み", "取り込む対象がありません。")
            return
        # 日付分割時は複数フォルダに書き込むので、すべてを確認対象にする
        existing = [
            d for d in import_plan.dest_dirs if d.is_dir() and any(d.iterdir())
        ]
        if existing:
            listed = "\n".join(f"  {d}" for d in existing[:10])
            more = f"\n  ... 他 {len(existing) - 10} 件" if len(existing) > 10 else ""
            answer = QMessageBox.question(
                self,
                "既存フォルダにマージ",
                f"次のフォルダには既にファイルがあります。\n\n{listed}{more}\n\n"
                "マージして取り込みますか？\n"
                "（既存ファイルは上書きされません。連番を避けて追加します）",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        self._stop_thumbnails()
        self._set_busy(True)
        self._progress.setVisible(True)
        self._progress.setRange(0, len(checked))

        # `checked` は `import_plan` と同じ計画から取り出したものである必要がある
        # （別々に作ると、コピー先が古い計画のままになる）
        worker = ImportWorker(import_plan, checked, self._catalog_path)
        worker.progress.connect(self._on_import_progress)
        worker.finished.connect(self._on_import_finished)
        worker.failed.connect(self._on_failed)
        self._import_worker = worker
        self._cancel_button.setVisible(True)
        self._cancel_button.setEnabled(True)
        self._cancel_button.setText("中断")
        self._run(worker)

    def _on_cancel(self) -> None:
        if self._import_worker is None:
            return
        # ワーカーは別スレッドにいるので、フラグを立てるだけ。
        # 実際に止まるのは処理中のカットが終わってから
        self._import_worker.cancel()
        self._cancel_button.setEnabled(False)
        self._cancel_button.setText("中断しています...")

    def _on_import_progress(self, index: int, total: int, name: str) -> None:
        self._progress.setValue(index)
        self._progress_label.setText(f"{index}/{total}  {name}")

    def _on_open_developer_toggled(self, checked: bool) -> None:
        self._config.launch_darktable_after_import = checked
        save_config(self._config, self._config_path)

    def _on_develop_jpeg_toggled(self, checked: bool) -> None:
        self._config.develop_jpeg = checked
        save_config(self._config, self._config_path)

    def _imported_folder(self, result) -> Path | None:
        """darktable で開くフォルダ。日付分割で複数になる場合は親を返す。"""
        dirs = {f.dest.parent for s in result.imported for f in s.files}
        if len(dirs) == 1:
            return dirs.pop()
        return self._dest_root() if dirs else None

    def _launch_developer(self, folder: Path) -> None:
        include_jpeg = self._develop_jpeg.isChecked()

        # JPEG を外す設定のとき、RAW の無い JPEG も巻き添えで読み込まれない。
        # darktable 側でペアだけを狙って外すことはできないため、ここで知らせる
        if not include_jpeg and folder_has_raw(folder):
            orphans = jpeg_only_names(folder)
            if orphans:
                listed = "\n".join(f"  {n}" for n in orphans[:10])
                more = f"\n  ... 他 {len(orphans) - 10} 件" if len(orphans) > 10 else ""
                QMessageBox.information(
                    self,
                    "darktable に読み込まれない JPEG",
                    f"RAW が対になっていない JPEG が {len(orphans)} 件あります。\n"
                    "darktable は JPEG をフォルダ単位でしか無視できないため、"
                    "これらも読み込まれません。\n\n"
                    f"{listed}{more}\n\n"
                    "必要なら［JPEG も現像対象にする］を入れて開き直してください。",
                )

        try:
            launch(folder, self._config.darktable_executable, include_jpeg)
        except DeveloperNotFoundError as e:
            QMessageBox.warning(self, "darktable", str(e))
        except OSError as e:
            QMessageBox.warning(
                self,
                "darktable",
                f"起動できませんでした: {e}\n\n"
                "既に darktable が起動している場合、多重起動はできません。",
            )

    def _on_import_finished(self, result) -> None:
        self._set_busy(False)
        self._progress.setVisible(False)
        self._progress_label.clear()
        self._cancel_button.setVisible(False)
        self._import_worker = None

        message = f"{len(result.imported)} カットを取り込みました。"
        if result.cancelled:
            message = (
                f"中断しました。{len(result.imported)} カットまで取り込み済みです。\n"
                "コピー済みのファイルは残しています。"
            )
        if result.failed:
            message += f"\n\n{len(result.failed)} カットが失敗しました:\n"
            message += "\n".join(
                f"  {s.shot.source_name}: {e}" for s, e in result.failed[:10]
            )

        folder = self._imported_folder(result)
        available = find_darktable(self._config.darktable_executable) is not None

        box = QMessageBox(self)
        if result.cancelled:
            title = "取り込みを中断しました"
        elif result.failed:
            title = "取り込み完了（一部失敗）"
        else:
            title = "取り込み完了"
        box.setWindowTitle(title)
        box.setIcon(
            QMessageBox.Icon.Warning
            if (result.failed or result.cancelled)
            else QMessageBox.Icon.Information
        )
        box.setText(message)
        open_button = None
        if available and folder is not None and result.imported:
            open_button = box.addButton(
                "darktable で開く", QMessageBox.ButtonRole.ActionRole
            )
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()

        # 1件も成功していないときは開かない
        if result.imported and folder is not None:
            if box.clickedButton() is open_button and open_button is not None:
                self._launch_developer(folder)
            elif self._open_developer.isChecked():
                self._launch_developer(folder)

        self._start_plan()  # 取り込み済みがグレーアウトされた状態に更新する

    # --- 共通 -------------------------------------------------------------

    def _run(self, worker) -> None:
        """ワーカーを専用スレッドで動かす。

        **ワーカーへの参照を必ず保持する。** `moveToThread()` は Qt に所有権を
        渡さないため、ローカル変数のままだと関数を抜けた時点で Python 側が
        ガベージコレクトし、スレッドが何も実行しないまま終わる。
        """
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        if hasattr(worker, "failed"):
            worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._drop_job(thread))

        self._jobs.append((thread, worker))
        thread.start()

    def _drop_job(self, thread: QThread) -> None:
        self._jobs = [(t, w) for t, w in self._jobs if t is not thread]

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for widget in (self._rescan_button, self._media_combo):
            widget.setEnabled(not busy)
        if busy:
            self._import_button.setEnabled(False)
        else:
            self._update_counts()  # 対象の有無で決める

    def _on_failed(self, message: str) -> None:
        self._set_busy(False)
        self._progress.setVisible(False)
        QMessageBox.critical(self, "エラー", message)

    def closeEvent(self, event) -> None:
        self._stop_thumbnails()
        self._config.window_width = self.width()
        self._config.window_height = self.height()
        save_config(self._config, self._config_path)
        for thread, _ in list(self._jobs):
            # 終了直後のスレッドは deleteLater 済みで C++ 側が消えていることがある。
            # その場合は触るだけで RuntimeError になるので握りつぶす
            try:
                thread.quit()
                thread.wait(3000)
            except RuntimeError:
                pass
        self._jobs.clear()
        super().closeEvent(event)
