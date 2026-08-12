"""`python -m photolab` のエントリポイント。

`pythonw.exe`（コンソール無し）から起動されると **stderr がどこにも出ない**。
起動時に落ちると何も分からなくなるので、traceback をログに残す。
"""

import sys
import traceback
from datetime import datetime

from photolab.cli import main


def _setup_console_encoding() -> None:
    """コンソールに UTF-8 で出せるようにする。

    PyInstaller で固めると UTF-8 で書き出す一方、日本語版 Windows の
    コンソールは CP932 で解釈するため文字化けする（2026-08-12 に実測）。
    コンソール側のコードページを UTF-8 に切り替えて合わせる。

    CP932 に無い文字（⚠ など）も出せるよう、コードページ側を変える方式にした。
    **元のコードページは終了時に戻す**（呼び出し元のシェルに影響を残さない）。
    コンソールが無い場合（`pythonw` / GUI 起動）は何もしない。
    """
    if sys.platform != "win32":
        return

    import atexit
    import ctypes

    kernel32 = ctypes.windll.kernel32
    previous = kernel32.GetConsoleOutputCP()
    if not previous:
        return  # コンソールが無い
    if previous != 65001 and kernel32.SetConsoleOutputCP(65001):
        atexit.register(kernel32.SetConsoleOutputCP, previous)

    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _log_crash(error: BaseException) -> "str | None":
    """traceback をログファイルに書く。書けたらそのパスを返す。"""
    try:
        from photolab.core.config import data_dir

        path = data_dir() / "error.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n===== {datetime.now().isoformat(timespec='seconds')} =====\n")
            traceback.print_exception(
                type(error), error, error.__traceback__, file=f
            )
        return str(path)
    except Exception:
        return None  # ログすら書けないなら諦める（元の例外を優先する）


if __name__ == "__main__":
    try:
        _setup_console_encoding()
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as e:  # noqa: BLE001
        log_path = _log_crash(e)
        traceback.print_exc()  # コンソールがあればそちらにも出す
        try:
            # GUI から起動された場合、コンソールが無いので画面に出す
            from PySide6.QtWidgets import QApplication, QMessageBox

            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(
                None,
                "Photolab の起動に失敗しました",
                f"{type(e).__name__}: {e}\n\n"
                + (f"詳細: {log_path}" if log_path else "ログを書けませんでした"),
            )
        except Exception:
            pass
        sys.exit(1)
