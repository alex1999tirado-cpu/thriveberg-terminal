from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "ajax_terminal" / "assets"
AMBER = (255, 176, 0, 255)
BLACK = (3, 4, 4, 255)
BORDER = (74, 87, 92, 255)

GLYPHS = {
    "T": (
        "11111",
        "00100",
        "00100",
        "00100",
        "00100",
        "00100",
        "00100",
    ),
    "B": (
        "11110",
        "10001",
        "10001",
        "11110",
        "10001",
        "10001",
        "11110",
    ),
    "_": (
        "00000",
        "00000",
        "00000",
        "00000",
        "00000",
        "00000",
        "11111",
    ),
}


def render_icon(size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size), BLACK)
    draw = ImageDraw.Draw(image)
    border = max(1, size // 128)
    inset = max(1, size // 24)
    radius = max(2, size // 7)
    draw.rounded_rectangle(
        (inset, inset, size - inset - 1, size - inset - 1),
        radius=radius,
        outline=BORDER,
        width=border,
    )

    # 17 columns: 5 for each glyph and one column between glyphs.
    usable = max(12, size - 2 * max(2, size // 8))
    cell = max(1, usable // 17)
    glyph_width = 17 * cell
    glyph_height = 7 * cell
    start_x = (size - glyph_width) // 2
    start_y = (size - glyph_height) // 2
    cursor_x = start_x
    for character in "TB_":
        for row, pattern in enumerate(GLYPHS[character]):
            for column, bit in enumerate(pattern):
                if bit == "1":
                    x0 = cursor_x + column * cell
                    y0 = start_y + row * cell
                    draw.rectangle((x0, y0, x0 + cell - 1, y0 + cell - 1), fill=AMBER)
        cursor_x += 6 * cell
    return image


def main() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    master = render_icon(1024)
    master.save(ASSET_DIR / "thriveberg-icon.png", optimize=True)
    frames = [render_icon(size) for size in (256, 128, 64, 48, 32, 24, 16)]
    frames[0].save(
        ASSET_DIR / "thriveberg.ico",
        format="ICO",
        append_images=frames[1:],
        sizes=[(size, size) for size in (256, 128, 64, 48, 32, 24, 16)],
    )


if __name__ == "__main__":
    main()
