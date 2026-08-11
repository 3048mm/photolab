"""設定とデータの置き場所。

Windows:
    %LOCALAPPDATA%\\Photolab\\catalog.db
    %LOCALAPPDATA%\\Photolab\\config.toml

Linux 移管時は `~/.local/share/photolab/` / `~/.config/photolab/` を使う
（architecture.md §9）。

`config.toml` の読みは標準の `tomllib`、書きは手書きのシリアライザで行う
（この程度のスキーマに TOML 書き出しの依存を足さない）。
"""

import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

APP_NAME = "Photolab"
CATALOG_FILENAME = "catalog.db"
CONFIG_FILENAME = "config.toml"


def data_dir() -> Path:
    """カタログなどの実データを置く場所。"""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / APP_NAME
        return Path.home() / "AppData" / "Local" / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME.lower()


def config_dir() -> Path:
    """設定ファイルを置く場所。Windows では data_dir と同じ。"""
    if sys.platform == "win32":
        return data_dir()
    return Path.home() / ".config" / APP_NAME.lower()


def default_catalog_path() -> Path:
    return data_dir() / CATALOG_FILENAME


def default_config_path() -> Path:
    return config_dir() / CONFIG_FILENAME


@dataclass(frozen=True)
class DestRoot:
    """登録した出力先の親フォルダ（計画書 §3.6）。

    毎回フォルダ参照ダイアログを開かずに済むよう、よく使う親を登録しておく。
    """

    label: str
    path: str


@dataclass
class Config:
    dest_roots: list[DestRoot] = field(default_factory=list)
    last_dest_root: str | None = None
    window_width: int = 1200
    window_height: int = 800
    darktable_executable: str = ""
    # 取り込んだらそのまま現像に入る流れが自然なので既定で有効にする
    launch_darktable_after_import: bool = True
    # RAW があるフォルダでは JPEG を現像対象にしない（ペアが二重に入るのを避ける）
    develop_jpeg: bool = False


def suggest_label(path: str, existing: "list[DestRoot]") -> str:
    """登録ボタンのラベルを提案する。

    フォルダ名の末尾を使い、既存の登録と衝突する場合は1つ上の階層まで含める。
    """
    parts = [p for p in Path(path).parts if p not in ("\\", "/")]
    if not parts:
        return path

    taken = {d.label for d in existing}
    for depth in range(1, len(parts) + 1):
        candidate = "\\".join(parts[-depth:])
        if candidate not in taken:
            return candidate
    return path


def _quote(value: str) -> str:
    """TOML の文字列にする。

    Windows のパスはバックスラッシュを含むため、原則リテラル文字列（`'...'`）を使う。
    リテラル文字列に入れられない `'` を含む場合だけ基本文字列に落とす。
    """
    if "'" not in value and "\n" not in value:
        return f"'{value}'"
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def load_config(path: Path | None = None) -> Config:
    """設定を読む。無い・壊れている場合は既定値を返す。"""
    path = Path(path) if path else default_config_path()
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return Config()

    window = data.get("window", {})
    darktable = data.get("darktable", {})
    return Config(
        dest_roots=[
            DestRoot(label=str(d.get("label", "")), path=str(d.get("path", "")))
            for d in data.get("dest_roots", [])
            if d.get("path")
        ],
        last_dest_root=data.get("last_dest_root"),
        window_width=int(window.get("width", 1200)),
        window_height=int(window.get("height", 800)),
        darktable_executable=str(darktable.get("executable", "")),
        launch_darktable_after_import=bool(darktable.get("launch_after_import", True)),
        develop_jpeg=bool(darktable.get("develop_jpeg", False)),
    )


def save_config(config: Config, path: Path | None = None) -> None:
    """設定を書く。フォルダが無ければ作る。"""
    path = Path(path) if path else default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = ["# Photolab の設定。GUI が書き換える。", ""]
    if config.last_dest_root:
        lines.append(f"last_dest_root = {_quote(config.last_dest_root)}")
        lines.append("")

    for dest_root in config.dest_roots:
        lines.append("[[dest_roots]]")
        lines.append(f"label = {_quote(dest_root.label)}")
        lines.append(f"path = {_quote(dest_root.path)}")
        lines.append("")

    lines.append("[window]")
    lines.append(f"width = {config.window_width}")
    lines.append(f"height = {config.window_height}")
    lines.append("")

    lines.append("[darktable]")
    lines.append(f"executable = {_quote(config.darktable_executable)}")
    launch = "true" if config.launch_darktable_after_import else "false"
    lines.append(f"launch_after_import = {launch}")
    lines.append(f"develop_jpeg = {'true' if config.develop_jpeg else 'false'}")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
