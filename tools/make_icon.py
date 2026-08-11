"""アプリアイコンを生成する。

    .\\venv\\Scripts\\python.exe tools\\make_icon.py

出力先は `photolab/ui/assets/`。生成物はリポジトリに含める（実行時には生成しない）。
再現できるようにスクリプトを残しているだけで、普段は実行不要。

意匠: 絞り（アパーチャー）。写真の道具であることが小さいサイズでも読み取れ、
形が単純なので 16px でも潰れない。
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT_DIR = Path(__file__).resolve().parent.parent / "photolab" / "ui" / "assets"
CANVAS = 1024  # 大きく描いて縮小する（アンチエイリアス目的）

# 配色。暗い下地に青のアクセントで、ライト/ダークどちらのタスクバーでも沈まない
BG_TOP = (38, 52, 71)
BG_BOTTOM = (17, 24, 39)
BLADE_LIGHT = (122, 190, 255)
BLADE_DARK = (58, 130, 214)
HOLE = (13, 18, 28)


def _vertical_gradient(size: int, top: tuple, bottom: tuple) -> Image.Image:
    gradient = Image.new("RGB", (1, size))
    for y in range(size):
        ratio = y / max(1, size - 1)
        gradient.putpixel(
            (0, y),
            tuple(int(top[i] + (bottom[i] - top[i]) * ratio) for i in range(3)),
        )
    return gradient.resize((size, size))


def _polygon(center: float, radius: float, count: int, offset: float) -> list:
    return [
        (
            center + radius * math.cos(offset + 2 * math.pi * i / count),
            center + radius * math.sin(offset + 2 * math.pi * i / count),
        )
        for i in range(count)
    ]


def build() -> Image.Image:
    image = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))

    # 角丸の下地（グラデーション）
    mask = Image.new("L", (CANVAS, CANVAS), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, CANVAS - 1, CANVAS - 1), radius=int(CANVAS * 0.22), fill=255
    )
    image.paste(_vertical_gradient(CANVAS, BG_TOP, BG_BOTTOM), (0, 0), mask)

    draw = ImageDraw.Draw(image)
    center = CANVAS / 2
    outer = CANVAS * 0.34
    inner = CANVAS * 0.15
    blades = 6
    start = -math.pi / 2

    # レンズの外周。円にすることで六角形のリングに見えないようにする
    draw.ellipse(
        (center - outer, center - outer, center + outer, center + outer),
        fill=BLADE_LIGHT + (255,),
    )

    # 羽根ごとの陰影。光が左上から当たっている想定で少しずつ暗くする
    for i in range(blades):
        angle = start + 2 * math.pi * i / blades
        next_angle = angle + 2 * math.pi / blades
        far = outer * 1.6
        ratio = abs(((i + 1.5) % blades) - blades / 2) / (blades / 2)
        shade = tuple(
            int(BLADE_LIGHT[c] + (BLADE_DARK[c] - BLADE_LIGHT[c]) * (1 - ratio) * 0.85)
            for c in range(3)
        )
        wedge = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
        ImageDraw.Draw(wedge).polygon(
            [
                (center, center),
                (center + far * math.cos(angle), center + far * math.sin(angle)),
                (center + far * math.cos(next_angle), center + far * math.sin(next_angle)),
            ],
            fill=shade + (255,),
        )
        disc = Image.new("L", (CANVAS, CANVAS), 0)
        ImageDraw.Draw(disc).ellipse(
            (center - outer, center - outer, center + outer, center + outer), fill=255
        )
        image.paste(wedge, (0, 0), Image.composite(wedge.getchannel("A"), disc, disc))

    draw = ImageDraw.Draw(image)

    # 中央の開口部（六角形）
    hole = _polygon(center, inner, blades, start)
    draw.polygon(hole, fill=HOLE + (255,))

    # 羽根の合わせ目。開口部の頂点から接線方向へ伸ばすと絞りらしくなる
    seam_width = int(CANVAS * 0.022)
    for i in range(blades):
        angle = start + 2 * math.pi * i / blades
        tip = (center + inner * math.cos(angle), center + inner * math.sin(angle))
        far_angle = angle - 1.05
        end = (center + outer * math.cos(far_angle), center + outer * math.sin(far_angle))
        draw.line([tip, end], fill=HOLE + (210,), width=seam_width)

    return image


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    icon = build()

    png = OUT_DIR / "photolab.png"
    icon.resize((256, 256), Image.Resampling.LANCZOS).save(png)

    ico = OUT_DIR / "photolab.ico"
    sizes = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256)]
    icon.save(ico, format="ICO", sizes=sizes)

    # 小さいサイズで潰れないかの確認用
    strip = Image.new("RGBA", (16 + 24 + 32 + 48 + 64 + 40, 64), (255, 255, 255, 255))
    x = 0
    for size in (16, 24, 32, 48, 64):
        strip.paste(icon.resize((size, size), Image.Resampling.LANCZOS), (x, 0))
        x += size + 8
    strip.save(OUT_DIR / "photolab_sizes_preview.png")

    print(f"生成: {png}")
    print(f"生成: {ico}")
    print(f"確認用: {OUT_DIR / 'photolab_sizes_preview.png'}")


if __name__ == "__main__":
    main()
