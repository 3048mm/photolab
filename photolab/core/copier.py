"""コピーとハッシュ照合。

写真データであり、**サイレントな破損は許容しない**（architecture.md §5.6）。
コピー後に書き込んだファイルを読み直して xxHash3 で照合する。
"""

import os
from pathlib import Path

import xxhash

# 30MB 級の NEF を扱うため、まとめて読まずチャンクで流す
_CHUNK_SIZE = 1024 * 1024


class CopyError(Exception):
    """コピーに失敗した。"""


class DestinationExistsError(CopyError):
    """コピー先に既にファイルがある。

    原本を上書きしないための多層防御。連番の採番（`core/naming.py`）で
    衝突は避けているが、それが破れた場合の最後の砦になる。
    """


class HashMismatchError(CopyError):
    """コピー後の照合に失敗した（転送中の破損）。"""


def hash_file(path: Path) -> str:
    """ファイルの xxHash3 (64bit) を16進文字列で返す。"""
    digest = xxhash.xxh3_64()
    with open(path, "rb") as f:
        while chunk := f.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_and_hash(src: Path, dest: Path) -> str:
    """コピーしながらコピー元のハッシュを計算し、それを返す。

    ハッシュのために元ファイルを読み直さない。カード読み出しが律速なので、
    データに触る回数を減らす（コピー元1回 + 照合の読み直し1回の計2パス）。
    """
    digest = xxhash.xxh3_64()
    with open(src, "rb") as reader, open(dest, "wb") as writer:
        while chunk := reader.read(_CHUNK_SIZE):
            digest.update(chunk)
            writer.write(chunk)
    return digest.hexdigest()


def copy_with_verify(src: Path, dest: Path) -> str:
    """コピーして照合し、確定したハッシュを返す。

    照合に失敗した場合は `HashMismatchError` を送出し、
    **書きかけのコピー先を削除する**。

    削除して安全なのは、`dest` が既に存在する場合は
    `DestinationExistsError` で先に弾いているため、
    ここで消すのは**この呼び出しで自分が作ったファイルに限られる**から。
    破損したファイルを正常な名前で残す方が、写真の資産としては危険である。
    """
    if dest.exists():
        raise DestinationExistsError(f"コピー先に既にファイルがあります: {dest}")

    dest.parent.mkdir(parents=True, exist_ok=True)

    source_hash = _copy_and_hash(src, dest)

    if hash_file(dest) != source_hash:
        # 自分が作ったファイルだけを消す
        dest.unlink(missing_ok=True)
        raise HashMismatchError(f"コピー後の照合に失敗しました: {src} -> {dest}")

    # 撮影時刻の手がかりになるので、元の更新日時を引き継ぐ
    stat = src.stat()
    os.utime(dest, (stat.st_atime, stat.st_mtime))

    return source_hash
