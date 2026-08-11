"""取り込みのオーケストレーション。

`plan()` と `execute()` を分ける（計画書 §3.5）。

- `plan()` は**副作用なし**で「どのファイルがどの名前でどこへ行くか /
  どれが取り込み済みか」を返す
- `execute()` が実際にコピーし、カタログへ登録する

GUI のプレビューと CLI のドライランが同じ `plan()` を使う。
"""

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from photolab.core.catalog import Catalog
from photolab.core.copier import CopyError, copy_with_verify
from photolab.core.dedup import DedupKey, build_key
from photolab.core.models import Shot
from photolab.core.naming import assign_basenames
from photolab.core.scanner import scan_card


@dataclass(frozen=True)
class PlannedFile:
    """1ファイルのコピー元と行き先。"""

    source: Path
    dest: Path


@dataclass(frozen=True)
class PlannedShot:
    """1カットの取り込み計画。"""

    shot: Shot
    dedup_key: DedupKey
    basename: str
    files: tuple[PlannedFile, ...]
    already_imported: bool

    @property
    def primary(self) -> PlannedFile:
        """代表ファイル（RAW 優先）。カタログに記録する対象。"""
        for f in self.files:
            if f.source.name == self.shot.source_name:
                return f
        return self.files[0]


@dataclass(frozen=True)
class ImportPlan:
    """取り込み計画。副作用なしで作られる。"""

    source_root: Path
    dest_root: Path
    shots: tuple[PlannedShot, ...]

    @property
    def new_shots(self) -> tuple[PlannedShot, ...]:
        """未取り込みのカット。既定ではこれだけを取り込む（Q3 合意）。"""
        return tuple(s for s in self.shots if not s.already_imported)

    @property
    def skipped(self) -> tuple[PlannedShot, ...]:
        """取り込み済みのカット。GUI ではグレーアウトする。"""
        return tuple(s for s in self.shots if s.already_imported)

    @property
    def dest_dirs(self) -> tuple[Path, ...]:
        """実際に書き込まれるフォルダの一覧（重複なし・名前順）。

        日付ごとの振り分けを有効にすると複数になる。
        GUI のプレビューと、既存フォルダへのマージ確認に使う。
        """
        found = {f.dest.parent for s in self.shots for f in s.files}
        return tuple(sorted(found))

    @property
    def warnings(self) -> tuple[PlannedShot, ...]:
        """弱いキーで判定しているカット。GUI で警告する（architecture.md §5.3）。"""
        return tuple(s for s in self.shots if s.dedup_key.is_fallback)


@dataclass(frozen=True)
class ImportResult:
    """取り込みの結果。"""

    batch_id: int
    imported: tuple[PlannedShot, ...]
    failed: tuple[tuple[PlannedShot, Exception], ...]
    cancelled: bool = False

    @property
    def ok(self) -> bool:
        return not self.failed and not self.cancelled


def _existing_names(dest_root: Path) -> list[str]:
    """出力先フォルダ直下の既存ファイル名。

    `darktable\\` サブフォルダは見ない（現像後の書き出し先であり、
    取り込みファイルの連番とは無関係 / architecture.md §5.2）。
    """
    if not dest_root.is_dir():
        return []
    return [p.name for p in dest_root.iterdir() if p.is_file()]


def plan(source_root: Path, dest_root: Path, catalog: Catalog) -> ImportPlan:
    """媒体を走査して取り込み計画を立てる。**書き込みは行わない。**

    走査（`scan_card`）はカードを読むため重い。出力先を変えただけで
    作り直したい場合は `build_plan()` を使う。
    """
    return build_plan(scan_card(source_root), source_root, dest_root, catalog)


def _dest_dir_for(shot: Shot, dest_root: Path, date_suffix: str) -> Path:
    """日付ごとの振り分け先。撮影日時が無いカットは `dest_root` 直下に置く。"""
    if shot.captured_at is None:
        return dest_root
    name = f"{shot.captured_at:%Y%m%d}"
    return dest_root / (f"{name} {date_suffix}" if date_suffix else name)


def build_plan(
    shots: "Sequence[Shot]",
    source_root: Path,
    dest_root: Path,
    catalog: Catalog,
    *,
    split_by_date: bool = False,
    date_suffix: str = "",
) -> ImportPlan:
    """走査済みのカットから計画を作る。**カードを読み直さない。**

    出力先が変わると、連番の衝突回避（既存ファイルの走査）と
    コピー先のパスが変わるため、作り直す必要がある。

    `split_by_date=True` のときは **`dest_root` を親フォルダとして扱い**、
    カットごとに `dest_root/<YYYYMMDD> <date_suffix>` へ振り分ける
    （`date_suffix` が空なら日付だけのフォルダ名になる）。
    既定は False。1枚のカードに複数日が混在していても1フォルダにまとめる運用が
    実在するため、自動では分割しない（architecture.md §7）。
    """
    if split_by_date:
        dest_dirs = [_dest_dir_for(s, dest_root, date_suffix) for s in shots]
    else:
        dest_dirs = [dest_root] * len(shots)

    # 連番の衝突回避は**フォルダごと**に行う必要がある
    by_dir: dict[Path, list[int]] = defaultdict(list)
    for index, directory in enumerate(dest_dirs):
        by_dir[directory].append(index)

    basenames: list[str] = [""] * len(shots)
    for directory, indexes in by_dir.items():
        assigned = assign_basenames(
            [shots[i] for i in indexes], _existing_names(directory)
        )
        for index, basename in zip(indexes, assigned):
            basenames[index] = basename

    keys = [build_key(s.to_metadata(), s.source_name, s.size) for s in shots]
    imported = catalog.imported_keys([k.value for k in keys])

    planned = []
    for shot, basename, key, directory in zip(shots, basenames, keys, dest_dirs):
        files = tuple(
            PlannedFile(source=f, dest=directory / f"{basename}{f.suffix}")
            for f in shot.files
        )
        planned.append(
            PlannedShot(
                shot=shot,
                dedup_key=key,
                basename=basename,
                files=files,
                already_imported=key.value in imported,
            )
        )
    return ImportPlan(source_root=source_root, dest_root=dest_root, shots=tuple(planned))


def execute(
    import_plan: ImportPlan,
    catalog: Catalog,
    selected: Sequence[PlannedShot] | None = None,
    progress: Callable[[int, int, PlannedShot], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> ImportResult:
    """計画を実行する。

    `selected` を渡さなければ**未取り込みのカットだけ**を取り込む。
    明示的に渡せば取り込み済みのカットも再取り込みできる（Q3 合意）。

    1カットのコピーに失敗しても**バッチ全体は止めない**。失敗したカットは
    カタログに登録せず `ImportResult.failed` に入れて返す。

    `should_cancel` が True を返したら**カットの区切りで中断**する。
    コピー途中のファイルを残さないため、1カットの処理中には割り込まない。
    **コピー済みのファイルは削除しない**（architecture.md §7）。
    中断したバッチは `aborted` として記録する。
    """
    targets = list(selected) if selected is not None else list(import_plan.new_shots)

    batch_id = catalog.start_batch(
        source_label=str(import_plan.source_root),
        dest_root=str(import_plan.dest_root),
    )

    imported: list[PlannedShot] = []
    failed: list[tuple[PlannedShot, Exception]] = []
    cancelled = False

    try:
        for index, planned_shot in enumerate(targets, start=1):
            # カットの区切りでだけ中断する。コピー途中には割り込まない
            if should_cancel is not None and should_cancel():
                cancelled = True
                break
            if progress:
                progress(index, len(targets), planned_shot)
            try:
                _import_one(planned_shot, catalog, batch_id)
            except CopyError as e:
                failed.append((planned_shot, e))
            else:
                imported.append(planned_shot)
    except BaseException:
        # 中断（Ctrl-C 等）。コピー済みファイルは消さない（計画書 §2.2）
        catalog.abort_batch(batch_id, file_count=len(imported))
        raise

    if cancelled:
        catalog.abort_batch(batch_id, file_count=len(imported))
    else:
        catalog.finish_batch(batch_id, file_count=len(imported))
    return ImportResult(
        batch_id=batch_id,
        imported=tuple(imported),
        failed=tuple(failed),
        cancelled=cancelled,
    )


def _import_one(planned_shot: PlannedShot, catalog: Catalog, batch_id: int) -> None:
    """1カット（RAW+JPEG なら両方）をコピーしてカタログに登録する。"""
    primary_hash = ""
    for planned_file in planned_shot.files:
        digest = copy_with_verify(planned_file.source, planned_file.dest)
        if planned_file is planned_shot.primary:
            primary_hash = digest

    shot = planned_shot.shot
    catalog.record_media(
        dedup_key=planned_shot.dedup_key.value,
        batch_id=batch_id,
        dest_path=str(planned_shot.primary.dest.parent),
        dest_name=planned_shot.primary.dest.name,
        is_fallback=planned_shot.dedup_key.is_fallback,
        camera_model=shot.camera_model,
        camera_serial=shot.camera_serial,
        shutter_count=shot.shutter_count,
        captured_at=shot.captured_at,
        source_name=shot.source_name,
        file_size=shot.size,
        content_hash=primary_hash,
    )
