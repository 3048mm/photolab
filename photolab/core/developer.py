"""現像ソフトの起動。

**内部状態には触らない。** コマンドラインで渡すだけであり、
現像ソフトのカタログ（darktable の `library.db` 等）を読みも書きもしない
（architecture.md §3.1）。乗り換える場合はここに定義を足すだけで済む。

対応:

| 現像ソフト | フォルダを開く | 備考 |
| :--- | :--- | :--- |
| darktable | ✅ `darktable <フォルダ>` | `--conf` で JPEG を除外できる |
| RapidRAW | ❌ | CLI はヘッドレス export 専用。起動だけ行う |
"""

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from photolab.core.models import RAW_SUFFIXES

_JPEG_SUFFIXES = frozenset({".JPG", ".JPEG"})

# darktable の「RAW 以外を無視する」設定。`--conf` で一時的に上書きでき、
# darktablerc には保存されない（`darktable --help`）。
_IGNORE_NONRAWS_KEY = "ui_last/import_ignore_nonraws"


class DeveloperNotFoundError(Exception):
    """現像ソフトの実行ファイルが見つからない。"""


@dataclass(frozen=True)
class DeveloperSpec:
    """現像ソフト1つ分の定義。"""

    key: str
    label: str
    windows_candidates: tuple[str, ...]
    posix_candidates: tuple[str, ...]
    # フォルダをコマンドライン引数で渡して開けるか
    opens_folder: bool
    # RAW+JPEG のペアで JPEG を除外する手段があるか
    can_ignore_jpeg: bool
    note: str = ""

    def candidates(self) -> tuple[str, ...]:
        return (
            self.windows_candidates if sys.platform == "win32" else self.posix_candidates
        )


DARKTABLE = DeveloperSpec(
    key="darktable",
    label="darktable",
    windows_candidates=(
        r"C:\Program Files\darktable\bin\darktable.exe",
        r"C:\Program Files (x86)\darktable\bin\darktable.exe",
    ),
    posix_candidates=("/usr/bin/darktable", "/usr/local/bin/darktable"),
    opens_folder=True,
    can_ignore_jpeg=True,
)

RAPIDRAW = DeveloperSpec(
    key="rapidraw",
    label="RapidRAW",
    windows_candidates=(
        r"%LOCALAPPDATA%\RapidRAW\RapidRAW.exe",
        r"C:\Program Files\RapidRAW\RapidRAW.exe",
    ),
    posix_candidates=("/usr/bin/rapidraw", "/usr/local/bin/rapidraw"),
    opens_folder=False,
    can_ignore_jpeg=False,
    note=(
        "CLI はヘッドレス export 専用で、フォルダを開く引数が無い。"
        "起動すると前回開いたフォルダが表示される。"
    ),
)

# 並び順が GUI のコンボボックスの並びになる。既定を先頭に置く
DEVELOPERS: dict[str, DeveloperSpec] = {
    RAPIDRAW.key: RAPIDRAW,
    DARKTABLE.key: DARKTABLE,
}
DEFAULT_DEVELOPER = RAPIDRAW.key


def get_spec(key: str) -> DeveloperSpec:
    """キーから定義を引く。未知のキーは既定に落とす。"""
    return DEVELOPERS.get(key, DEVELOPERS[DEFAULT_DEVELOPER])


def find_executable(spec: DeveloperSpec, configured: str = "") -> Path | None:
    """実行ファイルを探す。設定があればそれを優先する。"""
    if configured:
        path = Path(configured)
        return path if path.is_file() else None

    import os

    for candidate in spec.candidates():
        path = Path(os.path.expandvars(candidate))
        if path.is_file():
            return path
    return None


def folder_has_raw(folder: Path) -> bool:
    """フォルダ直下に RAW があるか。"""
    try:
        return any(p.suffix.upper() in RAW_SUFFIXES for p in folder.iterdir())
    except OSError:
        return False


def jpeg_only_names(folder: Path) -> list[str]:
    """RAW が対になっていない JPEG のファイル名。

    darktable で `ignore_nonraws` を有効にすると**このファイルも読み込まれない**。
    設定はフォルダ単位で JPEG を一律無視するもので、「ペアのときだけ無視する」
    ことはできないため。呼び出し側はこれを利用者に知らせること。
    """
    try:
        files = list(folder.iterdir())
    except OSError:
        return []
    raw_stems = {p.stem for p in files if p.suffix.upper() in RAW_SUFFIXES}
    return sorted(
        p.name
        for p in files
        if p.suffix.upper() in _JPEG_SUFFIXES and p.stem not in raw_stems
    )


def build_command(
    executable: Path,
    folder: Path,
    spec: DeveloperSpec,
    include_jpeg: bool = False,
) -> list[str]:
    """起動コマンドを組み立てる。

    フォルダを開けない現像ソフトには渡さない（渡すと引数として解釈されて
    予期しない動作になりうるため）。
    """
    command = [str(executable)]
    if not spec.opens_folder:
        return command

    if spec.can_ignore_jpeg and not include_jpeg and folder_has_raw(folder):
        command += ["--conf", f"{_IGNORE_NONRAWS_KEY}=TRUE"]
    command.append(str(folder))
    return command


def launch(
    folder: Path,
    configured: str = "",
    include_jpeg: bool = False,
    spec: DeveloperSpec | None = None,
) -> tuple[Path, Path | None]:
    """現像ソフトを起動する。

    **実際に渡した (実行ファイル, フォルダ) を返す。** フォルダを開けない
    現像ソフトでは2つ目が None になる。呼び出し側が元の引数をそのまま
    ログに出すと、渡した値と表示が食い違って混乱の元になるため
    （2026-08-11 に実際に起きた）。

    **必ず絶対パスで渡す。** 相対パスだと現像ソフト側の作業ディレクトリを
    基準に解決され、存在しないフォルダを渡すことになる。

    **起動を待たない**（`Popen` で投げっぱなしにする）。

    darktable は `library.db` をロックするため**多重起動できない**。
    既に起動している場合、ここでは成功扱いになり darktable 側が終了する。
    """
    spec = spec or DEVELOPERS[DEFAULT_DEVELOPER]
    executable = find_executable(spec, configured)
    if executable is None:
        raise DeveloperNotFoundError(
            f"{spec.label} の実行ファイルが見つかりません。設定でパスを指定してください。"
        )

    target = Path(folder).resolve()
    if not target.is_dir():
        raise FileNotFoundError(f"取り込み先フォルダがありません: {target}")

    creation_flags = 0
    if sys.platform == "win32":
        # 親プロセス（Photolab）を閉じても道連れにならないようにする
        creation_flags = getattr(subprocess, "DETACHED_PROCESS", 0)

    command = build_command(executable, target, spec, include_jpeg)
    subprocess.Popen(command, creationflags=creation_flags, close_fds=True)
    return executable, (target if spec.opens_folder else None)


# --- 後方互換 -----------------------------------------------------------


def find_darktable(configured: str = "") -> Path | None:
    """darktable の実行ファイルを探す（既存呼び出し向けの薄い別名）。"""
    return find_executable(DARKTABLE, configured)
