"""多重起動の防止。

常駐を二重に起動すると、同じカードで本体が2回開いてしまう。

ロックファイルに PID を書く方式にする。名前付きミューテックス（Windows）より
移植性があり、Linux へ移してもそのまま使える。

**強制終了でロックが残っても次の起動を妨げない。** 書かれている PID が
生きているかを確認し、死んでいれば奪う。
"""

import os
import sys
from pathlib import Path


def _is_running(pid: int) -> bool:
    """その PID のプロセスが生きているか。"""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)  # シグナルを送らずに存在確認する
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # 他ユーザーのプロセス = 生きている
    return True


class SingleInstance:
    """1つしか動かしたくないプロセスのためのロック。"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.acquired = False

    def running_pid(self) -> int | None:
        """ロックを持っている**生きている**プロセスの PID。

        ファイルが無い、内容が壊れている、書かれた PID が死んでいる場合は None。
        """
        try:
            text = self.path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            return None
        try:
            pid = int(text)
        except ValueError:
            return None  # 壊れている＝有効なロックではない
        return pid if _is_running(pid) else None

    def acquire(self) -> bool:
        """ロックを取る。取れたら True。"""
        if self.running_pid() is not None:
            return False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(str(os.getpid()), encoding="utf-8")
        except OSError:
            return False
        self.acquired = True
        return True

    def release(self) -> None:
        """ロックを離す。**自分が取ったときだけ**消す。"""
        if not self.acquired:
            return
        self.path.unlink(missing_ok=True)
        self.acquired = False

    def __enter__(self) -> "SingleInstance":
        self.acquire()
        return self

    def __exit__(self, *exc_info) -> None:
        self.release()
