"""取り込みカタログ（SQLite）。

**カタログは資産管理台帳ではない**（architecture.md §3.3）。答えるのは
「このカットは取り込み済みか？」の1問だけであり、レーティング・現像状態・
書き出し履歴は持たない。

スキーマは architecture.md §9。実体は `%LOCALAPPDATA%\\Photolab\\catalog.db`。
"""

import sqlite3
from datetime import datetime
from pathlib import Path

_SCHEMA = """
-- 取り込みバッチ（1回の取り込み操作）
CREATE TABLE IF NOT EXISTS import_batch (
    id           INTEGER PRIMARY KEY,
    started_at   TEXT NOT NULL,      -- ISO8601 ローカル時刻
    finished_at  TEXT,
    source_label TEXT,               -- ドライブレター / ボリューム名
    dest_root    TEXT,               -- 出力先フォルダ
    file_count   INTEGER,
    status       TEXT NOT NULL       -- running / done / aborted
);

-- 取り込み済みメディア（重複判定のためだけに存在する）
CREATE TABLE IF NOT EXISTS imported_media (
    id              INTEGER PRIMARY KEY,
    dedup_key       TEXT NOT NULL UNIQUE,   -- architecture.md §5.3
    is_fallback     INTEGER NOT NULL DEFAULT 0,  -- 弱いキーで登録されたか
    camera_model    TEXT,
    camera_serial   TEXT,
    shutter_count   INTEGER,
    captured_at     TEXT,                   -- ISO8601 ローカル時刻
    source_name     TEXT,                   -- カード上の元ファイル名 (DSC_1234.NEF)
    dest_path       TEXT NOT NULL,
    dest_name       TEXT NOT NULL,
    file_size       INTEGER,
    content_hash    TEXT,                   -- xxh3
    imported_at     TEXT NOT NULL,
    import_batch_id INTEGER NOT NULL REFERENCES import_batch(id)
);

CREATE INDEX IF NOT EXISTS idx_media_captured ON imported_media(captured_at);
CREATE INDEX IF NOT EXISTS idx_media_batch    ON imported_media(import_batch_id);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);
"""


class Catalog:
    """カタログへの接続。コンテキストマネージャとして使う。"""

    SCHEMA_VERSION = 1

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._create_schema()

    # --- ライフサイクル -------------------------------------------------

    def __enter__(self) -> "Catalog":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    def _create_schema(self) -> None:
        with self._conn:
            self._conn.executescript(_SCHEMA)
            row = self._conn.execute("SELECT version FROM schema_version").fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)",
                    (self.SCHEMA_VERSION,),
                )

    # --- 問い合わせ -----------------------------------------------------

    def table_names(self) -> set[str]:
        rows = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        return {r["name"] for r in rows}

    def schema_version(self) -> int:
        row = self._conn.execute("SELECT version FROM schema_version").fetchone()
        return row["version"]

    # --- 取り込みバッチ -------------------------------------------------

    def start_batch(self, source_label: str, dest_root: str) -> int:
        """取り込みバッチを開始し、その id を返す。"""
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO import_batch (started_at, source_label, dest_root, status)"
                " VALUES (?, ?, ?, 'running')",
                (datetime.now().isoformat(timespec="seconds"), source_label, dest_root),
            )
        return int(cur.lastrowid)

    def _close_batch(self, batch_id: int, status: str, file_count: int) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE import_batch SET finished_at = ?, file_count = ?, status = ?"
                " WHERE id = ?",
                (
                    datetime.now().isoformat(timespec="seconds"),
                    file_count,
                    status,
                    batch_id,
                ),
            )

    def finish_batch(self, batch_id: int, file_count: int) -> None:
        self._close_batch(batch_id, "done", file_count)

    def abort_batch(self, batch_id: int, file_count: int) -> None:
        """中断として記録する。**コピー済みファイルの削除はしない**（§7）。"""
        self._close_batch(batch_id, "aborted", file_count)

    def batch_status(self, batch_id: int) -> str | None:
        row = self._conn.execute(
            "SELECT status FROM import_batch WHERE id = ?", (batch_id,)
        ).fetchone()
        return row["status"] if row else None

    # --- 取り込み済みメディア -------------------------------------------

    def record_media(
        self,
        dedup_key: str,
        batch_id: int,
        dest_path: str,
        dest_name: str,
        *,
        is_fallback: bool = False,
        camera_model: str | None = None,
        camera_serial: str | None = None,
        shutter_count: int | None = None,
        captured_at: datetime | None = None,
        source_name: str | None = None,
        file_size: int | None = None,
        content_hash: str | None = None,
    ) -> None:
        """取り込み済みとして記録する。

        同じ `dedup_key` が既にあれば**新規レコードを作らず上書きする**
        （Q3 合意 / architecture.md §3.3）。カタログは履歴を持たない。
        `dest_path` は「どこへ入れたか」の参考情報であり、正確な追跡は保証しない。
        """
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO imported_media (
                    dedup_key, is_fallback, camera_model, camera_serial, shutter_count,
                    captured_at, source_name, dest_path, dest_name, file_size,
                    content_hash, imported_at, import_batch_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dedup_key) DO UPDATE SET
                    is_fallback     = excluded.is_fallback,
                    camera_model    = excluded.camera_model,
                    camera_serial   = excluded.camera_serial,
                    shutter_count   = excluded.shutter_count,
                    captured_at     = excluded.captured_at,
                    source_name     = excluded.source_name,
                    dest_path       = excluded.dest_path,
                    dest_name       = excluded.dest_name,
                    file_size       = excluded.file_size,
                    content_hash    = excluded.content_hash,
                    imported_at     = excluded.imported_at,
                    import_batch_id = excluded.import_batch_id
                """,
                (
                    dedup_key,
                    int(is_fallback),
                    camera_model,
                    camera_serial,
                    shutter_count,
                    captured_at.isoformat() if captured_at else None,
                    source_name,
                    dest_path,
                    dest_name,
                    file_size,
                    content_hash,
                    datetime.now().isoformat(timespec="seconds"),
                    batch_id,
                ),
            )

    def is_imported(self, dedup_key: str) -> bool:
        """このカットは取り込み済みか？ — カタログの唯一の存在意義。"""
        row = self._conn.execute(
            "SELECT 1 FROM imported_media WHERE dedup_key = ?", (dedup_key,)
        ).fetchone()
        return row is not None

    def imported_keys(self, dedup_keys: "list[str] | tuple[str, ...]") -> set[str]:
        """渡したキーのうち取り込み済みのものを返す。

        GUI のサムネイルグリッドが1枚ずつ問い合わせずに済むようにするための一括版。
        """
        keys = list(dedup_keys)
        if not keys:
            return set()
        placeholders = ",".join("?" * len(keys))
        rows = self._conn.execute(
            f"SELECT dedup_key FROM imported_media WHERE dedup_key IN ({placeholders})",
            keys,
        ).fetchall()
        return {r["dedup_key"] for r in rows}

    def find(self, dedup_key: str) -> sqlite3.Row | None:
        row = self._conn.execute(
            "SELECT * FROM imported_media WHERE dedup_key = ?", (dedup_key,)
        ).fetchone()
        return row

    def media_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS n FROM imported_media").fetchone()
        return int(row["n"])
