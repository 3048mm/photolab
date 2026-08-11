"""現像ソフト（darktable）の起動。

**内部状態には触らない。** `darktable <フォルダ>` とコマンドラインで渡すだけであり、
`library.db` を読みも書きもしない（architecture.md §3.1）。
乗り換える場合はここのコマンドを差し替えるだけで済む。
"""

import subprocess
import sys
from pathlib import Path

# Windows の既定インストール先。見つからなければ設定で指定してもらう。
_WINDOWS_CANDIDATES = (
    r"C:\Program Files\darktable\bin\darktable.exe",
    r"C:\Program Files (x86)\darktable\bin\darktable.exe",
)
_POSIX_CANDIDATES = ("/usr/bin/darktable", "/usr/local/bin/darktable")


class DeveloperNotFoundError(Exception):
    """darktable の実行ファイルが見つからない。"""


def find_darktable(configured: str = "") -> Path | None:
    """darktable の実行ファイルを探す。設定があればそれを優先する。"""
    if configured:
        path = Path(configured)
        return path if path.is_file() else None

    candidates = _WINDOWS_CANDIDATES if sys.platform == "win32" else _POSIX_CANDIDATES
    for candidate in candidates:
        path = Path(candidate)
        if path.is_file():
            return path
    return None


def launch(folder: Path, configured: str = "") -> tuple[Path, Path]:
    """取り込み先フォルダを darktable で開く。

    **実際に渡した (実行ファイル, フォルダ) を返す。** 呼び出し側が元の引数を
    そのままログに出すと、渡した値と表示が食い違って混乱の元になるため
    （2026-08-11 に実際に起きた）。

    `darktable [OPTIONS] [IMAGE_FILE | IMAGE_FOLDER]`（darktable 5.6 で確認）。
    フォルダを渡すとフィルムロールとして読み込まれる。

    **必ず絶対パスで渡す。** 相対パスだと darktable 側の作業ディレクトリを基準に
    解決され、存在しないフォルダを渡すことになって何も起きない（2026-08-11 に実際に踏んだ）。

    **起動を待たない**（`Popen` で投げっぱなしにする）。取り込み後の GUI が
    darktable の終了を待つ形にしてはならない。

    darktable は `library.db` をロックするため**多重起動できない**。
    既に起動している場合、ここでは成功扱いになり darktable 側が終了する。
    呼び出し側はその旨を案内するに留めること。
    """
    executable = find_darktable(configured)
    if executable is None:
        raise DeveloperNotFoundError(
            "darktable の実行ファイルが見つかりません。設定でパスを指定してください。"
        )

    target = Path(folder).resolve()
    if not target.is_dir():
        raise FileNotFoundError(f"取り込み先フォルダがありません: {target}")

    creation_flags = 0
    if sys.platform == "win32":
        # 親プロセス（Photolab）を閉じても darktable が道連れにならないようにする
        creation_flags = getattr(subprocess, "DETACHED_PROCESS", 0)

    subprocess.Popen(
        [str(executable), str(target)],
        creationflags=creation_flags,
        close_fds=True,
    )
    return executable, target
