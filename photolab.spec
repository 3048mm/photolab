# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller の定義。

    .\\venv\\Scripts\\pyinstaller.exe photolab.spec --noconfirm

**onedir でビルドする。** onefile は起動のたびに 100MB 超を展開するので体感が悪く、
PySide6 (LGPLv3) を動的リンクのまま保つ点でも onedir が素直
（利用者が Qt の DLL を差し替えられる状態を保てる）。

実行ファイルは2つ作る。

  Photolab.exe     コンソール無し。引数なしで GUI、`watch` で常駐
  photolab-cli.exe コンソールあり。`doctor` や `import` を使うため

両方とも同じ COLLECT を共有するので、DLL が二重に入ることはない。
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

APP_NAME = "Photolab"
ROOT = Path(SPECPATH)
ICON = ROOT / "photolab" / "ui" / "assets" / "photolab.ico"

# アプリのアイコンと、同梱するライセンス表示
datas = [
    (str(ROOT / "photolab" / "ui" / "assets"), "photolab/ui/assets"),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "NOTICE.md"), "."),
]

# rawpy は LibRaw の DLL を持つ。フックが拾い損ねる環境があるので明示しておく
hiddenimports = collect_submodules("rawpy")

# 使わない重量級モジュール。含めると数百 MB 増える
excludes = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtQuick",
    "PySide6.QtQml",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtSerialPort",
    "PySide6.QtWebSockets",
    "PySide6.QtWebChannel",
    "tkinter",
    "matplotlib",
    "pytest",
    # 開発時の答え合わせ専用。GPL なので配布物に入れてはならない
    "pyexiv2",
]

analysis = Analysis(
    [str(ROOT / "photolab" / "__main__.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(analysis.pure)

gui_exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # コンソール窓を出さない。失敗時は error.log に残す
    icon=str(ICON),
)

cli_exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="photolab-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # doctor / import の出力を見せる
    icon=str(ICON),
)

coll = COLLECT(
    gui_exe,
    cli_exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)
