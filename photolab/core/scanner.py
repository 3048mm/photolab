"""媒体の検出とカードの走査。

実機カード（Nikon Z6 / FAT32）の構造:

    L:\\
      ├─ DCIM\\102NCZ_6\\   ← 取り込み対象はここだけ
      ├─ NIKON\\Z_6         ← カメラの管理ファイル
      ├─ System Volume Information\\
      └─ NIKON001.DSC       ← カメラの管理ファイル

除外対象は architecture.md §5.5。**取り込み対象は許可リストで決める**
（知らない拡張子は持って行かない）。
"""

import string
import sys
from dataclasses import dataclass
from pathlib import Path

from photolab.core.metadata import read_metadata
from photolab.core.models import Shot

# 取り込み対象はここだけを見る。カードのルートにはカメラの管理ファイルがある。
DCIM_DIR = "DCIM"

# 取り込み対象の拡張子。許可リスト方式にする。
MEDIA_SUFFIXES = frozenset({".NEF", ".JPG", ".JPEG", ".MOV", ".MP4"})

# カットの代表ファイルとして優先する拡張子。
RAW_SUFFIXES = frozenset({".NEF"})

# 許可リストに載っていても明示的に除外するもの（architecture.md §5.5）。
# 現状は許可リストで弾けるが、意図を残すために名前で持っておく。
EXCLUDED_NAMES = frozenset({"NC_FLLST.DAT"})
EXCLUDED_SUFFIXES = frozenset({".THM", ".LRV"})


def is_excluded(path: Path) -> bool:
    """コピー対象外か判定する。"""
    name = path.name
    if name.startswith("."):  # 隠しファイル
        return True
    if name.upper() in EXCLUDED_NAMES:
        return True
    suffix = path.suffix.upper()
    if suffix in EXCLUDED_SUFFIXES:
        return True
    return suffix not in MEDIA_SUFFIXES


def has_dcim(root: Path) -> bool:
    """媒体候補か判定する。DCIM/ の有無で見る（architecture.md §5.1）。"""
    return (root / DCIM_DIR).is_dir()


@dataclass(frozen=True)
class MediaCandidate:
    """検出した媒体。GUI のメディア選択に出す。"""

    root: Path
    label: str

    @property
    def display_name(self) -> str:
        """実機カードのラベルは 'NIKON Z 6' のように機種名が入っていた。"""
        return f"{self.label} ({self.root})" if self.label else str(self.root)


def _volume_label(root: Path) -> str:
    """ボリュームラベルを取得する。取れなければ空文字を返す。"""
    if sys.platform != "win32":
        return ""
    import ctypes

    buffer = ctypes.create_unicode_buffer(261)
    ok = ctypes.windll.kernel32.GetVolumeInformationW(
        ctypes.c_wchar_p(str(root)), buffer, 261, None, None, None, None, 0
    )
    return buffer.value if ok else ""


def _is_removable(root: Path) -> bool:
    """リムーバブルドライブか判定する。"""
    if sys.platform != "win32":
        return True  # Linux 移管時はマウントポイントの列挙側で絞る
    import ctypes

    DRIVE_REMOVABLE = 2
    return ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(str(root))) == DRIVE_REMOVABLE


def find_media() -> list[MediaCandidate]:
    """リムーバブルドライブを列挙し、DCIM/ を持つものを候補として返す。

    Windows 依存の部分はここに閉じ込める。Linux 移管時はこの関数だけ差し替える
    （AutoPlay 連携はしない方針 / architecture.md §5.1）。
    """
    candidates = []
    for letter in string.ascii_uppercase:
        root = Path(f"{letter}:\\")
        try:
            if not root.is_dir() or not _is_removable(root) or not has_dcim(root):
                continue
        except OSError:
            continue
        candidates.append(MediaCandidate(root=root, label=_volume_label(root)))
    return candidates


def _primary(files: "list[Path]") -> Path:
    """カットの代表ファイル。RAW があれば RAW を選ぶ。

    重複判定キーと元ファイル名の基準になる。RAW+JPEG では
    シリアル+ショットカウントが一致するのでどちらでもよいが、
    退避キー（元ファイル名 + サイズ）が効く場面のために固定しておく。
    """
    for f in files:
        if f.suffix.upper() in RAW_SUFFIXES:
            return f
    return files[0]


def _build_shot(files: "list[Path]") -> Shot:
    primary = _primary(files)
    meta = read_metadata(primary)
    return Shot(
        captured_at=meta.captured_at,
        shutter_count=meta.shutter_count,
        source_name=primary.name,
        files=tuple(sorted(files)),
        size=primary.stat().st_size,
        camera_model=meta.camera_model,
        camera_serial=meta.camera_serial,
        duration_seconds=meta.duration_seconds,
    )


def scan_card(root: Path) -> list[Shot]:
    """媒体を走査してカットの一覧を返す。

    **DCIM/ 配下だけを対象にする。** 実機カードのルートには `NIKON\\` や
    `NIKON001.DSC` といったカメラの管理ファイルが置かれているため。

    RAW + JPEG は拡張子を除いた名前が同じものを 1 カットにまとめる。
    """
    dcim = root / DCIM_DIR
    if not dcim.is_dir():
        return []

    groups: dict[tuple[Path, str], list[Path]] = {}
    for path in sorted(dcim.rglob("*")):
        if not path.is_file() or is_excluded(path):
            continue
        groups.setdefault((path.parent, path.stem), []).append(path)

    return [_build_shot(files) for files in groups.values()]
