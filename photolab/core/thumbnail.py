"""サムネイルの生成とキャッシュ。

方針（architecture.md §5.4）:

- **RAW（NEF / CR2 / CR3 / ARW）は埋め込み JPEG プレビューを取り出す。** フルデコード（デモザイク）はしない。
  `rawpy.extract_thumb()` は埋め込み JPEG のバイト列をデコードせず返すため高速
- **JPG は自身をデコードして縮小する。** Z50 は JPEG 中心であり、
  JPEG 単独カットは一級市民として扱う
- 生成したサムネイルは**ローカルにキャッシュする**。カード読み出しが律速のため

動画のサムネイルは Phase 1 では作らない（GUI が代替表示する）。
"""

import io
import struct
from pathlib import Path
from typing import Sequence

import rawpy
import xxhash
from PIL import Image

from photolab.core.config import data_dir
from photolab.core.metadata import iter_boxes
from photolab.core.models import RAW_SUFFIXES

# サムネイルの長辺。グリッドの表示サイズに対して余裕を持たせる
DEFAULT_MAX_SIZE = 512

# 保存時の JPEG 品質。表示用なので画質より容量を優先する
_JPEG_QUALITY = 85

_JPEG_SUFFIXES = frozenset({".JPG", ".JPEG"})
_VIDEO_SUFFIXES = frozenset({".MOV", ".MP4"})

# Nikon の MOV は `moov/udta/NCDT` に JPEG を埋め込んでいる（実測 2026-08-11）。
#   NCVW 1920x1080 / NCM1 640x360 / NCTH 160x120
# 大きい順に試す。動画のデコードは不要なので ffmpeg 等に依存しない。
_NIKON_PREVIEW_ATOMS = ("NCVW", "NCM1", "NCTH")


def jpeg_dimensions(data: bytes) -> tuple[int, int]:
    """JPEG のバイト列から (幅, 高さ) を読む。デコードはしない。"""
    reader = io.BytesIO(data)
    if reader.read(2) != b"\xff\xd8":
        raise ValueError("JPEG ではありません")
    while True:
        marker = reader.read(2)
        if len(marker) < 2 or marker[0] != 0xFF:
            raise ValueError("SOF マーカーが見つかりません")
        (length,) = struct.unpack(">H", reader.read(2))
        # SOF0-SOF15。ただし DHT(C4) / JPG(C8) / DAC(CC) は除く
        if 0xC0 <= marker[1] <= 0xCF and marker[1] not in (0xC4, 0xC8, 0xCC):
            reader.read(1)  # サンプル精度
            height, width = struct.unpack(">HH", reader.read(4))
            return width, height
        reader.seek(length - 2, 1)


def _nikon_video_preview(path: Path) -> bytes | None:
    """Nikon の MOV から埋め込み JPEG を取り出す。

    `moov/udta/NCDT` に複数の解像度で入っている。動画をデコードしないので
    ffmpeg 等の重い依存が要らない。Nikon 以外の動画では None を返す。
    """
    end = path.stat().st_size
    with open(path, "rb") as f:
        for name, body, box_end in iter_boxes(f, end):
            if name != "moov":
                continue
            f.seek(body)
            for sub_name, sub_body, sub_end in iter_boxes(f, box_end):
                if sub_name != "udta":
                    continue
                f.seek(sub_body)
                for udta_name, udta_body, udta_end in iter_boxes(f, sub_end):
                    if udta_name != "NCDT":
                        continue
                    f.seek(udta_body)
                    found: dict[str, bytes] = {}
                    for atom, atom_body, atom_end in iter_boxes(f, udta_end):
                        if atom in _NIKON_PREVIEW_ATOMS:
                            f.seek(atom_body)
                            found[atom] = f.read(atom_end - atom_body)
                    for preferred in _NIKON_PREVIEW_ATOMS:
                        data = found.get(preferred)
                        if data and data[:3] == b"\xff\xd8\xff":
                            return data
    return None


def _embedded_preview(path: Path) -> bytes | None:
    """縮小前の元データを取り出す。"""
    suffix = path.suffix.upper()
    # CR2 / ARW は TIFF、CR3 は ISOBMFF だが、どれも rawpy で埋め込み JPEG を取り出せる
    if suffix in RAW_SUFFIXES:
        with rawpy.imread(str(path)) as raw:
            thumb = raw.extract_thumb()
        if thumb.format == rawpy.ThumbFormat.JPEG:
            return thumb.data
        return None
    if suffix in _JPEG_SUFFIXES:
        return path.read_bytes()
    if suffix in _VIDEO_SUFFIXES:
        return _nikon_video_preview(path)
    return None  # 未対応フォーマット


def render_thumbnail(preview: bytes, max_size: int = DEFAULT_MAX_SIZE) -> bytes | None:
    """取り出した JPEG バイト列を縮小して返す。**CPU 律速の処理**。

    I/O を含まないので、スレッドプールに載せて並列化する価値がある
    （`generate_many()` 参照）。
    """
    try:
        image = Image.open(io.BytesIO(preview))
        # libjpeg の DCT スケーリングで 1/2〜1/8 に間引いてデコードする。
        # 6048px のプレビューをそのまま展開しないため大幅に速い
        image.draft("RGB", (max_size, max_size))
        image = image.convert("RGB")
        image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

        out = io.BytesIO()
        image.save(out, format="JPEG", quality=_JPEG_QUALITY)
        return out.getvalue()
    except Exception:
        return None


def thumbnail_bytes(path: Path, max_size: int = DEFAULT_MAX_SIZE) -> bytes | None:
    """サムネイルの JPEG バイト列を返す。作れなければ None。

    1枚の異常でグリッド全体を落とさないため、**例外を投げない**。
    """
    try:
        preview = _embedded_preview(path)
    except Exception:
        # rawpy / OS のどの層からでも例外が来うる
        return None
    if preview is None:
        return None
    return render_thumbnail(preview, max_size)


class ThumbnailCache:
    """生成したサムネイルをローカルに置いておく。

    キーは「元ファイルのパス + 更新日時 + サイズ + 長辺」から作る。
    元ファイルが差し替わればキーも変わるので、古いキャッシュを返すことはない。
    """

    def __init__(self, cache_dir: Path | None = None):
        self.cache_dir = Path(cache_dir) if cache_dir else data_dir() / "thumbnails"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _key(self, path: Path, max_size: int) -> str:
        stat = path.stat()
        raw = f"{path.resolve()}:{stat.st_mtime_ns}:{stat.st_size}:{max_size}"
        return xxhash.xxh3_64(raw.encode("utf-8")).hexdigest()

    def path_for(self, path: Path, max_size: int = DEFAULT_MAX_SIZE) -> Path:
        return self.cache_dir / f"{self._key(path, max_size)}.jpg"

    def get(self, path: Path, max_size: int = DEFAULT_MAX_SIZE) -> bytes | None:
        """キャッシュがあればそれを、無ければ生成して保存してから返す。"""
        try:
            cached = self.path_for(path, max_size)
        except OSError:
            return None

        if cached.is_file():
            return cached.read_bytes()

        data = thumbnail_bytes(path, max_size)
        if data is None:
            return None

        self.store(cached, data)
        return data

    @staticmethod
    def store(cached: Path, data: bytes) -> None:
        """生成途中のファイルを読ませないため、別名で書いてから差し替える。"""
        temp = cached.with_suffix(".part")
        temp.write_bytes(data)
        temp.replace(cached)

    def generate_many(
        self,
        paths: "Sequence[Path]",
        max_size: int = DEFAULT_MAX_SIZE,
        workers: int = 4,
    ) -> "dict[Path, bytes | None]":
        """複数ファイルのサムネイルをまとめて用意する。

        **カードからの読み出しは直列、縮小だけを並列**にする。

        実測（2026-08-10 / Nikon Z6 の SD カード / 30カット）:

        | 工程 | 直列 | 4並列 | 8並列 |
        | :--- | ---: | ---: | ---: |
        | I/O（プレビュー取り出し） | 156.5 ms/枚 | — | — |
        | CPU（縮小・再エンコード） | 84.8 ms/枚 | 22.3 ms/枚 | 15.4 ms/枚 |

        I/O が支配的（カード実効 40 MB/s）で、並列読み出しはシーク競合により
        かえって遅くなる。一方 CPU 側は 8 並列で 5.5 倍になる。
        両者を分けると 241 ms/枚 → 172 ms/枚（355 カットで約 86 秒 → 61 秒）。
        """
        from concurrent.futures import ThreadPoolExecutor

        result: dict[Path, bytes | None] = {}
        pending: list[tuple[Path, Path, bytes]] = []

        for path in paths:
            try:
                cached = self.path_for(path, max_size)
            except OSError:
                result[path] = None
                continue
            if cached.is_file():
                result[path] = cached.read_bytes()
                continue
            try:
                preview = _embedded_preview(path)  # ここだけが I/O
            except Exception:
                preview = None
            if preview is None:
                result[path] = None
                continue
            pending.append((path, cached, preview))

        if pending:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                rendered = pool.map(
                    lambda item: render_thumbnail(item[2], max_size), pending
                )
                for (path, cached, _), data in zip(pending, rendered):
                    if data is not None:
                        self.store(cached, data)
                    result[path] = data
        return result
