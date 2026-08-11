"""カタログの点検と修復。

カタログと実ファイルは独立に動く。取り込んだ後にファイルを手で消したり、
誤って取り込んだ分を削除したりすると、**カタログだけが「取り込み済み」と
言い続ける**。そのカットは次回グレーアウトされ、既定で選択されなくなる。

ここで検出して直す。

> **消すのはカタログの記録だけ。写真そのものには絶対に触れない。**
"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from photolab.core.catalog import Catalog
from photolab.core.copier import hash_file


@dataclass(frozen=True)
class CatalogReport:
    """点検結果。"""

    total: int
    missing: tuple[sqlite3.Row, ...]
    hash_mismatch: tuple[sqlite3.Row, ...]

    @property
    def ok(self) -> bool:
        return not self.missing and not self.hash_mismatch


def check_catalog(catalog: Catalog, verify_hash: bool = False) -> CatalogReport:
    """カタログの記録と実ファイルを突き合わせる。

    `verify_hash` はファイルを全部読むため重い。既定では存在確認だけ行う。
    """
    missing: list[sqlite3.Row] = []
    mismatch: list[sqlite3.Row] = []

    rows = catalog.all_media()
    for row in rows:
        path = Path(row["dest_path"]) / row["dest_name"]
        if not path.is_file():
            missing.append(row)
            continue
        if verify_hash and row["content_hash"]:
            try:
                if hash_file(path) != row["content_hash"]:
                    mismatch.append(row)
            except OSError:
                missing.append(row)

    return CatalogReport(
        total=len(rows), missing=tuple(missing), hash_mismatch=tuple(mismatch)
    )


def remove_missing(catalog: Catalog, report: CatalogReport) -> int:
    """実ファイルが無い記録を消す。消した件数を返す。

    **写真は消さない。** 記録が消えたカットは次回「未取り込み」に戻るので、
    取り込み直せる。
    """
    keys = [row["dedup_key"] for row in report.missing]
    return catalog.remove_media(keys)
