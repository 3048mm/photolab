"""ドメインモデル。

複数のモジュール（`naming` / `scanner` / `importer`）が共有する値オブジェクトを置く。
GUI 非依存であり、PySide6 を import しない。
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


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
