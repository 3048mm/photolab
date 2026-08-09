"""EXIF / Nikon MakerNote / QuickTime メタデータの抽出。

**標準ライブラリのみで実装する。** `pyexiv2`(GPL-3.0) / `exiv2`(GPL-2.0) に
依存しないため（architecture.md §7 / NOTICE.md）。

取得できる情報（architecture.md §5.3）:

- `camera_model` / `camera_serial` / `shutter_count` / `captured_at`

NEF は素の TIFF であり、Nikon MakerNote は `Nikon\\0` + version(2) + padding(2) の
10バイトヘッダの後に**埋め込み TIFF ヘッダ**が続く。MakerNote 内のオフセットは
この埋め込みヘッダを起点とする。`0x001d` SerialNumber と `0x00a7` ShutterCount は
平文で格納されている。
"""

import struct
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

# --- TIFF ---------------------------------------------------------------

# TIFF タグ型 -> (1要素のバイト数, struct フォーマット)
_TYPE_INFO = {
    1: (1, "B"),    # BYTE
    2: (1, "s"),    # ASCII
    3: (2, "H"),    # SHORT
    4: (4, "I"),    # LONG
    5: (8, "II"),   # RATIONAL
    7: (1, "B"),    # UNDEFINED
    9: (4, "i"),    # SLONG
    10: (8, "ii"),  # SRATIONAL
}

_TAG_MAKE = 0x010F
_TAG_MODEL = 0x0110
_TAG_EXIF_IFD = 0x8769
_TAG_DATETIME_ORIGINAL = 0x9003
_TAG_MAKERNOTE = 0x927C

_TAG_NIKON_SERIAL = 0x001D
_TAG_NIKON_SHUTTER_COUNT = 0x00A7

# MakerNote は先頭数百KBに収まるが、安全側に取る
_HEADER_READ_SIZE = 2 * 1024 * 1024

# EXIF の日時形式
_EXIF_DATETIME_FORMAT = "%Y:%m:%d %H:%M:%S"

# --- QuickTime ----------------------------------------------------------

# QuickTime のエポックは 1904-01-01 00:00:00（ローカル時刻で書かれる）
_QT_EPOCH = datetime(1904, 1, 1)

_STILL_SUFFIXES = {".NEF", ".JPG", ".JPEG"}
_VIDEO_SUFFIXES = {".MOV", ".MP4"}


@dataclass(frozen=True)
class Metadata:
    """1ファイルから読み取れたメタデータ。

    取得できなかった項目は None になる。破損ファイルでも例外を投げず
    「取れたものだけ」を返す方針とする。1枚の異常で取り込みバッチ全体を
    落とさないため。
    """

    camera_model: str | None = None
    camera_serial: str | None = None
    shutter_count: int | None = None
    captured_at: datetime | None = None

    @property
    def has_still_key(self) -> bool:
        """静止画の重複判定キー（シリアル + ショットカウント）を作れるか。"""
        return self.camera_serial is not None and self.shutter_count is not None


def _read_ifd(buf: bytes, base: int, ifd_offset: int, endian: str) -> dict:
    """1つの IFD を読み `{タグ: 値}` を返す。`base` は値オフセットの起点。"""
    entries: dict[int, object] = {}
    pos = base + ifd_offset
    if pos + 2 > len(buf):
        return entries
    (count,) = struct.unpack_from(endian + "H", buf, pos)
    pos += 2
    for _ in range(count):
        if pos + 12 > len(buf):
            break
        tag, typ, num = struct.unpack_from(endian + "HHI", buf, pos)
        value_field = pos + 8
        pos += 12
        if typ not in _TYPE_INFO:
            continue
        size, fmt = _TYPE_INFO[typ]
        total = size * num
        if total > 4:
            # 4バイトに収まらない値は、オフセット先に置かれる
            (offset,) = struct.unpack_from(endian + "I", buf, value_field)
            data_pos = base + offset
        else:
            data_pos = value_field
        if data_pos < 0 or data_pos + total > len(buf):
            continue
        if typ == 2:  # ASCII
            raw = buf[data_pos:data_pos + total]
            entries[tag] = raw.split(b"\x00")[0].decode("ascii", "replace")
        elif typ == 7:  # UNDEFINED（MakerNote 等）
            entries[tag] = buf[data_pos:data_pos + total]
        else:
            values = struct.unpack_from(endian + fmt * num, buf, data_pos)
            entries[tag] = values[0] if len(values) == 1 else values
    return entries


def _parse_tiff_header(buf: bytes, base: int) -> tuple[str | None, int]:
    """TIFF ヘッダから (エンディアン, IFD0 オフセット) を返す。"""
    magic = buf[base:base + 2]
    if magic == b"II":
        endian = "<"
    elif magic == b"MM":
        endian = ">"
    else:
        return None, 0
    (ifd0,) = struct.unpack_from(endian + "I", buf, base + 4)
    return endian, ifd0


def _find_exif_in_jpeg(buf: bytes) -> int | None:
    """JPEG の APP1 セグメントから TIFF 部分の開始位置を探す。"""
    pos = 2
    while pos + 4 < len(buf):
        if buf[pos] != 0xFF:
            return None
        marker = buf[pos + 1]
        (seg_len,) = struct.unpack_from(">H", buf, pos + 2)
        if marker == 0xE1 and buf[pos + 4:pos + 10] == b"Exif\x00\x00":
            return pos + 10
        if marker == 0xDA:  # SOS 以降は画像データ
            return None
        pos += 2 + seg_len
    return None


def _parse_nikon_makernote(raw: bytes) -> tuple[str | None, int | None]:
    """Nikon type3 MakerNote から (serial, shutter_count) を返す。"""
    if not raw.startswith(b"Nikon\x00"):
        return None, None
    tiff_base = 10  # "Nikon\0" + version(2) + padding(2)
    endian, ifd0 = _parse_tiff_header(raw, tiff_base)
    if endian is None:
        return None, None
    tags = _read_ifd(raw, tiff_base, ifd0, endian)
    serial = tags.get(_TAG_NIKON_SERIAL)
    shutter_count = tags.get(_TAG_NIKON_SHUTTER_COUNT)
    return (
        serial if isinstance(serial, str) else None,
        shutter_count if isinstance(shutter_count, int) else None,
    )


def _parse_exif_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, _EXIF_DATETIME_FORMAT)
    except ValueError:
        return None


def read_still_metadata(path: Path) -> Metadata:
    """NEF / JPG からメタデータを読む。"""
    with open(path, "rb") as f:
        buf = f.read(_HEADER_READ_SIZE)

    if buf[:2] == b"\xff\xd8":  # JPEG
        base = _find_exif_in_jpeg(buf)
        if base is None:
            return Metadata()
    else:  # TIFF / NEF
        base = 0

    endian, ifd0 = _parse_tiff_header(buf, base)
    if endian is None:
        return Metadata()

    ifd0_tags = _read_ifd(buf, base, ifd0, endian)
    model = ifd0_tags.get(_TAG_MODEL)

    exif_offset = ifd0_tags.get(_TAG_EXIF_IFD)
    if not isinstance(exif_offset, int):
        return Metadata(camera_model=model if isinstance(model, str) else None)

    exif_tags = _read_ifd(buf, base, exif_offset, endian)
    captured_at = _parse_exif_datetime(exif_tags.get(_TAG_DATETIME_ORIGINAL))

    makernote = exif_tags.get(_TAG_MAKERNOTE)
    serial, shutter_count = (
        _parse_nikon_makernote(makernote) if isinstance(makernote, bytes) else (None, None)
    )

    return Metadata(
        camera_model=model if isinstance(model, str) else None,
        camera_serial=serial,
        shutter_count=shutter_count,
        captured_at=captured_at,
    )


def _iter_boxes(f, end: int):
    """現在位置から `end` までの QuickTime ボックスを列挙する。

    `(型, データ開始位置, ボックス終端)` を返す。
    """
    while f.tell() + 8 <= end:
        start = f.tell()
        header = f.read(8)
        if len(header) < 8:
            return
        size, box_type = struct.unpack(">I4s", header)
        if size == 1:  # 64bit 拡張サイズ
            (size,) = struct.unpack(">Q", f.read(8))
            body = start + 16
        elif size == 0:  # ファイル終端まで
            size = end - start
            body = start + 8
        else:
            body = start + 8
        if size < 8:
            return
        yield box_type.decode("ascii", "replace"), body, start + size
        f.seek(start + size)


def read_video_metadata(path: Path) -> Metadata:
    """MOV / MP4 の `moov/mvhd` から撮影日時を読む。

    Nikon の MOV は `creation_time` に**ローカル時刻**を書いている
    （規格上は UTC だがカメラでは一般的な逸脱）。タイムゾーン変換はしない
    （architecture.md §5.2）。
    """
    end = path.stat().st_size
    with open(path, "rb") as f:
        for box_type, body, box_end in _iter_boxes(f, end):
            if box_type != "moov":
                continue
            f.seek(body)
            for sub_type, sub_body, _ in _iter_boxes(f, box_end):
                if sub_type != "mvhd":
                    continue
                f.seek(sub_body)
                version = f.read(1)[0]
                f.read(3)  # flags
                if version == 1:
                    (created,) = struct.unpack(">Q", f.read(8))
                else:
                    (created,) = struct.unpack(">I", f.read(4))
                return Metadata(captured_at=_QT_EPOCH + timedelta(seconds=created))
    return Metadata()


def read_metadata(path: Path) -> Metadata:
    """拡張子に応じてメタデータを読む。

    読めない・壊れている場合も**例外を投げず**空の Metadata を返す。
    1枚の異常で取り込みバッチ全体を落とさないため。
    """
    suffix = path.suffix.upper()
    try:
        if suffix in _STILL_SUFFIXES:
            return read_still_metadata(path)
        if suffix in _VIDEO_SUFFIXES:
            return read_video_metadata(path)
    except (OSError, struct.error, ValueError, IndexError, OverflowError):
        return Metadata()
    return Metadata()
