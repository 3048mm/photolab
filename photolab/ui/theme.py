"""配色と共通の見た目。

**色は原則としてパレット（`QPalette`）から取る。** ハードコードするとテーマの片方で
読めなくなる（`.claude/skills/photolab-gui/SKILL.md`）。

例外は「自分で下地を描くバッジ」で、下地の色を自分で決めているためテーマに依存しない。
"""

from pathlib import Path

from PySide6.QtGui import QColor, QFont, QIcon, QPalette

ASSETS_DIR = Path(__file__).resolve().parent / "assets"

# --- 基本の配色（ダーク） -----------------------------------------------
# 写真を見るツールなので、周囲が暗い方が画像の色が正しく見える
WINDOW = QColor("#2b2f36")
WINDOW_TEXT = QColor("#e6e8eb")
BASE = QColor("#22262c")          # 入力欄など
BUTTON = QColor("#3a4048")
DISABLED_TEXT = QColor("#7c848e")

# サムネイルグリッド。Lightroom のように「タイルが敷き詰められ、
# タイル間の少し濃い線が格子になる」構成にする
GRID_BASE = QColor("#565c65")    # 1タイルの下地。ウィンドウより明るいグレー
GRID_VOID = QColor("#484d55")    # タイルが無い余白。タイルより少しだけ落とす
TILE_BORDER = QColor("#3b4046")  # タイル間の区切り線（隣接して格子になる）
TILE_SELECTED = QColor("#6b7481")  # 選択中のタイルは下地を持ち上げる

# 未チェックの写真にかぶせる暗幕。
# 明るいタイルの上では不透明度を下げると「白く飛ぶ」方向になり、
# 「暗くして目立たなくする」意図と逆になるため、暗い色を重ねる
UNCHECKED_VEIL = QColor(12, 15, 20, 130)
# 写真そのものの縁。下地から浮かせるため明るい細線を回す
THUMB_BORDER = QColor(226, 231, 238, 150)

# 既定のフォントサイズ（pt）。OS 既定（9pt 前後）だと小さいので少し上げる
FONT_POINT_SIZE_DELTA = 1.5
FONT_FAMILIES = ["Yu Gothic UI", "Meiryo UI", "Noto Sans CJK JP", "sans-serif"]

# --- アクセント ---------------------------------------------------------
# ライト/ダークどちらの背景でも十分なコントラストが出る青。アイコンと揃えている
ACCENT = QColor("#3a82d6")
ACCENT_LIGHT = QColor("#7abeff")

# 注意を引く黄。EXIF が取れない等の警告に使う
WARNING = QColor("#f2c14e")
WARNING_INK = QColor("#4a3800")

# --- サムネイルの上に重ねるバッジ ---------------------------------------
BADGE_BG = QColor(16, 20, 28, 190)
BADGE_INK = QColor(236, 240, 246)

# 取り込み済みは「状態の説明」であって操作対象ではない。
# アクセント色はチェック・選択（操作に関わるもの）のために取っておく。
# 暗い写真の上でも見えるよう明るい下地にし、印を暗くする
IMPORTED_BG = QColor(226, 231, 238, 235)
IMPORTED_INK = QColor(38, 43, 51)

# --- 余白 ---------------------------------------------------------------
GAP = 8
SECTION_GAP = 12


def base_font() -> QFont:
    """アプリ全体のフォント。

    Windows の既定フォントは日本語が不格好になることがあるため明示する。
    Linux 移管を考えて Noto Sans CJK JP をリストに残す。
    """
    font = QFont()
    font.setFamilies(FONT_FAMILIES)
    font.setPointSizeF(font.pointSizeF() + FONT_POINT_SIZE_DELTA)
    return font


def dark_palette() -> QPalette:
    """ダーク配色。写真の周囲を暗くして画像の色を正しく見せる。"""
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, WINDOW)
    palette.setColor(QPalette.ColorRole.WindowText, WINDOW_TEXT)
    palette.setColor(QPalette.ColorRole.Base, BASE)
    palette.setColor(QPalette.ColorRole.AlternateBase, WINDOW)
    palette.setColor(QPalette.ColorRole.Text, WINDOW_TEXT)
    palette.setColor(QPalette.ColorRole.Button, BUTTON)
    palette.setColor(QPalette.ColorRole.ButtonText, WINDOW_TEXT)
    palette.setColor(QPalette.ColorRole.ToolTipBase, BASE)
    palette.setColor(QPalette.ColorRole.ToolTipText, WINDOW_TEXT)
    palette.setColor(QPalette.ColorRole.Highlight, ACCENT)
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, DISABLED_TEXT)

    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, DISABLED_TEXT)
    return palette


def apply(app) -> None:
    """アプリ全体に配色・フォント・アイコンを適用する。

    ダーク配色を効かせるには Fusion スタイルが要る。Windows 標準スタイルは
    パレットの多くを無視して OS のテーマ色で描いてしまう。
    """
    app.setStyle("Fusion")
    app.setPalette(dark_palette())
    app.setFont(base_font())
    app.setWindowIcon(app_icon())

    # Windows のタイトルバーもダークにする。パレットはクライアント領域にしか
    # 効かないため、これを指定しないと枠だけ明るいままになる
    hints = app.styleHints()
    if hasattr(hints, "setColorScheme"):
        from PySide6.QtCore import Qt

        hints.setColorScheme(Qt.ColorScheme.Dark)


def app_icon() -> QIcon:
    """アプリ/ウィンドウのアイコン。"""
    ico = ASSETS_DIR / "photolab.ico"
    if ico.is_file():
        return QIcon(str(ico))
    png = ASSETS_DIR / "photolab.png"
    return QIcon(str(png)) if png.is_file() else QIcon()


def selection_tint(palette: QPalette) -> QColor:
    """選択中のセルに敷く色。パレットの強調色を薄めて使う。"""
    color = QColor(palette.color(QPalette.ColorRole.Highlight))
    color.setAlpha(48)
    return color


def selection_border(palette: QPalette) -> QColor:
    return QColor(palette.color(QPalette.ColorRole.Highlight))


def muted_text(palette: QPalette) -> QColor:
    """補助的な文字（パスの表示など）。"""
    return palette.color(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText
    )
