"""ドメインモデル。

複数のモジュール（`naming` / `scanner` / `importer`）が共有する値オブジェクトを置く。
GUI 非依存であり、PySide6 を import しない。
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from photolab.core.metadata import Metadata


@dataclass(frozen=True)
class Shot:
    """取り込み対象の 1 カット。

    RAW + JPEG のペアは 1 カットとして扱い、同じ basename を共有する
    （architecture.md §5.2）。`files` にはそのカットを構成する全ファイルが入る。

    `source_name` と `size` は**代表ファイル**（RAW があれば RAW）のもの。
    重複判定の退避キー（§5.3）がこれを使う。

    `captured_at` が None のカットはリネームせず元ファイル名のまま取り込む。
    """

    captured_at: datetime | None
    shutter_count: int | None
    source_name: str
    files: tuple[Path, ...] = field(default=())
    size: int = 0
    camera_model: str | None = None
    camera_serial: str | None = None
    duration_seconds: float | None = None  # 動画のみ。GUI のバッジに使う

    @property
    def is_video(self) -> bool:
        return any(f.suffix.upper() in (".MOV", ".MP4") for f in self.files)

    @property
    def has_raw(self) -> bool:
        return any(f.suffix.upper() == ".NEF" for f in self.files)

    @property
    def composition(self) -> str:
        """このカットが何で構成されているか。GUI のバッジに出す。

        現像の元があるか（RAW か JPEG か）が一目で分かるようにするため。
        """
        if self.is_video:
            return ""
        has_jpeg = any(f.suffix.upper() in (".JPG", ".JPEG") for f in self.files)
        if self.has_raw and has_jpeg:
            return "RAW+JPG"
        if self.has_raw:
            return "RAW"
        return "JPG"

    @property
    def is_jpeg_only(self) -> bool:
        """RAW が無く JPEG だけのカット。

        Z50 は JPEG 中心で、Z6 のカードにも混ざる（architecture.md §5.4）。
        現像の元が無いので、GUI で区別できるようにする。
        """
        return not self.is_video and not self.has_raw

    def to_metadata(self) -> "Metadata":
        """重複判定キーの生成（`core/dedup.py`）に渡すための変換。"""
        from photolab.core.metadata import Metadata

        return Metadata(
            camera_model=self.camera_model,
            camera_serial=self.camera_serial,
            shutter_count=self.shutter_count,
            captured_at=self.captured_at,
        )
