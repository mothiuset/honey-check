"""Genera el icono empaquetado. Pillow es solo de desarrollo: no viaja en el ejecutable."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

TARGET = Path(__file__).parents[1] / "src" / "honey_check" / "presentation" / "web" / "icon.ico"


def draw(size: int) -> Image.Image:
    scale = size / 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas = ImageDraw.Draw(image)

    def box(*values: float) -> tuple[float, float, float, float]:
        left, top, right, bottom = (v * scale for v in values)
        return left, top, right, bottom

    canvas.rounded_rectangle(box(11, 19, 53, 60), radius=11 * scale, fill=(232, 150, 20, 255))
    canvas.rounded_rectangle(box(16, 36, 48, 54), radius=5 * scale, fill=(255, 216, 110, 255))
    canvas.rounded_rectangle(box(14, 9, 50, 21), radius=4 * scale, fill=(122, 74, 16, 255))
    canvas.rounded_rectangle(box(19, 4, 45, 11), radius=3 * scale, fill=(170, 106, 26, 255))
    return image


def main() -> None:
    sizes = [(16, 16), (20, 20), (24, 24), (32, 32), (48, 48), (256, 256)]
    draw(256).save(TARGET, format="ICO", sizes=sizes)
    print(TARGET)


if __name__ == "__main__":
    main()
