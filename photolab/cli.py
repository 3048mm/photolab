"""コマンドラインインターフェース。

GUI を載せる前に end-to-end を通すためのもの（計画書 §2.2）。
GUI と同じ `core/importer.py` の `plan()` / `execute()` を使う。

    python -m photolab list
    python -m photolab import --source L:\\ --dest "tmp\\out\\20260809 テスト" [--dry-run]
"""

import argparse
import sys
from pathlib import Path

from photolab.core.catalog import Catalog
from photolab.core.config import default_catalog_path, load_config
from photolab.core.developer import (
    DEVELOPERS,
    DeveloperNotFoundError,
    folder_has_raw,
    get_spec,
    jpeg_only_names,
    launch,
)
from photolab.core.importer import ImportPlan, build_plan, execute
from photolab.core.maintenance import check_catalog, remove_missing
from photolab.core.scanner import find_media, scan_card


def _print_media() -> int:
    candidates = find_media()
    if not candidates:
        print("メディアが見つかりません（DCIM を持つリムーバブルドライブ）")
        return 1
    for c in candidates:
        print(c.display_name)
    return 0


def _run_doctor(args: argparse.Namespace) -> int:
    """カタログと実ファイルの食い違いを点検する。"""
    catalog_path = Path(args.catalog) if args.catalog else default_catalog_path()
    print(f"カタログ: {catalog_path}")

    with Catalog(catalog_path) as catalog:
        stale = catalog.abort_stale_batches()
        if stale:
            print(f"中断のまま残っていたバッチを aborted にしました: {stale} 件")

        report = check_catalog(catalog, verify_hash=args.verify_hash)
        print(f"登録: {report.total} 件")
        print(f"  実ファイルが無い  : {len(report.missing)} 件")
        if args.verify_hash:
            print(f"  ハッシュ不一致    : {len(report.hash_mismatch)} 件")

        for row in report.missing[:20]:
            print(f"    無し: {row['dest_path']}\\{row['dest_name']}")
        if len(report.missing) > 20:
            print(f"    ... 他 {len(report.missing) - 20} 件")
        for row in report.hash_mismatch[:20]:
            print(f"    不一致: {row['dest_path']}\\{row['dest_name']}")

        if report.ok:
            print("問題ありません。")
            return 0

        if not args.fix:
            print("\n--fix を付けると、実ファイルが無い記録をカタログから削除します。")
            print("（写真そのものは削除しません）")
            return 1

        removed = remove_missing(catalog, report)
        print(f"\nカタログから {removed} 件の記録を削除しました（写真は削除していません）。")
        print("該当のカットは次回から『未取り込み』として扱われます。")

        if report.hash_mismatch:
            print(
                f"⚠ ハッシュ不一致 {len(report.hash_mismatch)} 件は自動では直しません。"
                "内容が変わっている可能性があります。",
                file=sys.stderr,
            )
            return 1
        return 0


def _print_plan(import_plan: ImportPlan) -> None:
    print(f"コピー元: {import_plan.source_root}")
    dirs = import_plan.dest_dirs
    if len(dirs) > 1:
        print(f"出力先  : {import_plan.dest_root} の下に {len(dirs)} フォルダ")
        for directory in dirs:
            print(f"          {directory.name}")
    else:
        print(f"出力先  : {import_plan.dest_root}")
    print(
        f"カット  : {len(import_plan.shots)} "
        f"(未取り込み {len(import_plan.new_shots)} / 取り込み済み {len(import_plan.skipped)})"
    )
    if import_plan.warnings:
        print(f"警告    : {len(import_plan.warnings)} カットが弱いキーで判定されています")

    for planned_shot in import_plan.shots[:10]:
        mark = "skip" if planned_shot.already_imported else "copy"
        warn = " (弱いキー)" if planned_shot.dedup_key.is_fallback else ""
        names = ",".join(f.dest.name for f in planned_shot.files)
        print(f"  [{mark}] {planned_shot.shot.source_name:16} -> {names}{warn}")
    if len(import_plan.shots) > 10:
        print(f"  ... 他 {len(import_plan.shots) - 10} カット")


def _run_import(args: argparse.Namespace) -> int:
    # 絶対パスに直してから使う。相対のままだとカタログに作業ディレクトリ依存の
    # 記録が残り、darktable に渡すパスも解決先が変わってしまう
    source = Path(args.source).resolve()
    dest = Path(args.dest).resolve()
    catalog_path = Path(args.catalog) if args.catalog else default_catalog_path()

    with Catalog(catalog_path) as catalog:
        import_plan = build_plan(
            scan_card(source),
            source,
            dest,
            catalog,
            split_by_date=args.split_by_date,
        )
        _print_plan(import_plan)

        if args.dry_run:
            print("\n--dry-run のため実行しません")
            return 0

        if not import_plan.new_shots:
            print("\n取り込むカットがありません")
            # 取り込むものが無くても、出力先が既にあるなら開いてよい
            _open_darktable(args, dest)
            return 0

        def progress(index: int, total: int, planned_shot) -> None:
            print(f"  [{index}/{total}] {planned_shot.basename}", end="\r")

        print()
        result = execute(import_plan, catalog, progress=progress)
        print(f"\n取り込み完了: {len(result.imported)} カット (batch={result.batch_id})")
        for planned_shot, error in result.failed:
            print(f"  失敗: {planned_shot.shot.source_name}: {error}", file=sys.stderr)

        # 失敗しかしなかった場合は開かない
        if result.imported:
            _open_darktable(args, import_plan.dest_dirs[0] if len(
                import_plan.dest_dirs) == 1 else dest)

        return 0 if result.ok else 1


def _open_darktable(args: argparse.Namespace, folder: Path) -> None:
    if not args.open_darktable:
        return
    config = load_config()
    spec = get_spec(args.developer or config.developer)
    include_jpeg = args.develop_jpeg

    try:
        # 表示は launch() が返した「実際に渡した値」を使う（元の引数を出さない）
        executable, opened = launch(
            folder, config.executable_for(spec.key), include_jpeg, spec
        )
        print(f"{spec.label} を起動しました: {executable}")

        if opened is None:
            print(f"  ※ {spec.note}")
            print(f"  取り込み先: {folder}")
            return

        print(f"  読み込ませたフォルダ: {opened}")

        if spec.can_ignore_jpeg and not include_jpeg and folder_has_raw(opened):
            print("  RAW があるため JPEG は読み込ませていません（--develop-jpeg で変更）")
            orphans = jpeg_only_names(opened)
            if orphans:
                print(
                    f"  ⚠ RAW が対になっていない JPEG {len(orphans)} 件も"
                    "読み込まれません:",
                    file=sys.stderr,
                )
                for name in orphans[:10]:
                    print(f"      {name}", file=sys.stderr)

        # 空フォルダを渡しても darktable は何も表示しない。気づけるようにしておく
        count = sum(1 for p in opened.iterdir() if p.is_file())
        if count == 0:
            print(
                "  ⚠ このフォルダにファイルがありません。"
                "darktable には何も表示されません。",
                file=sys.stderr,
            )
        else:
            print(f"  フォルダ内のファイル: {count} 件")
        if spec.key == "darktable":
            print(
                "  ※ darktable が既に起動している場合、"
                "ロックのため新しいプロセスは何もせず終了します。"
            )
    except (DeveloperNotFoundError, OSError) as e:
        print(f"{spec.label} を起動できませんでした: {e}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="photolab", description="RAW 取り込みツール")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="取り込み可能なメディアを一覧する")
    sub.add_parser("gui", help="GUI を起動する")

    p_doctor = sub.add_parser(
        "doctor", help="カタログと実ファイルの食い違いを点検する"
    )
    p_doctor.add_argument("--catalog", help="カタログのパス（既定は %%LOCALAPPDATA%%）")
    p_doctor.add_argument(
        "--fix",
        action="store_true",
        help="実ファイルが無い記録をカタログから削除する（写真は削除しない）",
    )
    p_doctor.add_argument(
        "--verify-hash",
        action="store_true",
        help="ハッシュも照合する（全ファイルを読むので遅い）",
    )

    p_import = sub.add_parser("import", help="メディアから取り込む")
    p_import.add_argument("--source", required=True, help="メディアのルート (例: L:\\)")
    p_import.add_argument("--dest", required=True, help="出力先の撮影フォルダ")
    p_import.add_argument("--catalog", help="カタログのパス（既定は %%LOCALAPPDATA%%）")
    p_import.add_argument(
        "--dry-run", action="store_true", help="計画だけ表示して実行しない"
    )
    p_import.add_argument(
        "--split-by-date",
        action="store_true",
        help="撮影日ごとのフォルダに振り分ける（--dest を親フォルダとして扱う）",
    )
    p_import.add_argument(
        "--open-darktable",
        action="store_true",
        help="取り込み後に darktable で開く",
    )
    p_import.add_argument(
        "--develop-jpeg",
        action="store_true",
        help="darktable に JPEG も読み込ませる（既定: RAW があるフォルダでは JPEG を除外）",
    )
    p_import.add_argument(
        "--developer",
        choices=sorted(DEVELOPERS),
        help="起動する現像ソフト（既定は config.toml の設定）",
    )

    args = parser.parse_args(argv)
    if args.command == "list":
        return _print_media()
    if args.command == "doctor":
        return _run_doctor(args)
    if args.command == "gui":
        # PySide6 は GUI を使うときだけ import する（CLI だけなら不要）
        from photolab.ui.app import main as gui_main

        return gui_main()
    return _run_import(args)
