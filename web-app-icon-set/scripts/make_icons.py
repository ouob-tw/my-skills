# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow"]
# ///
"""Cut one square artwork into a web app icon set.

Usage: uv run make_icons.py <square-source.png> <out-dir> [--radius 0.225] [--small-source head.png]

With --small-source, the 16/32 px favicons and favicon.ico are cut from that
close-up instead (sharpened, smaller corner radius); everything else uses the
main source.
"""
import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


def rounded(src: Image.Image, size: int, radius: float, sharpen: int = 0) -> Image.Image:
    # Draw the mask at 8x and downsample so the curved edge is anti-aliased.
    big = size * 8
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, big - 1, big - 1), radius=round(big * radius), fill=255)
    img = src.resize((size, size), Image.LANCZOS)
    if sharpen:
        img = img.filter(ImageFilter.UnsharpMask(radius=0.6, percent=sharpen, threshold=0))
    img = img.convert("RGBA")
    img.putalpha(mask.resize((size, size), Image.LANCZOS))
    return img


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("out")
    ap.add_argument("--radius", type=float, default=0.225, help="corner radius as a fraction of the side")
    ap.add_argument("--small-source", help="square close-up used only for the 16/32 px favicons and favicon.ico")
    a = ap.parse_args()

    src = Image.open(a.source).convert("RGB")
    if src.width != src.height:
        raise SystemExit(f"source must be square, got {src.width}x{src.height}")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    # Shown as-is by browsers and some launchers: corners baked in, transparent outside.
    for size, name in [(192, "icon-192.png"), (512, "icon-512.png")]:
        rounded(src, size, a.radius).save(out / name, optimize=True)
    if a.small_source:
        small = Image.open(a.small_source).convert("RGB")
        if small.width != small.height:
            raise SystemExit(f"small source must be square, got {small.width}x{small.height}")
        # At 16 px a 22.5% corner eats ~4 px of the picture: use smaller corners and sharpen after shrinking.
        for size, name, radius, sharpen in [(16, "favicon-16.png", 0.12, 70), (32, "favicon-32.png", 0.15, 60), (48, "favicon-48.png", 0.18, 50)]:
            rounded(small, size, radius, sharpen).save(out / name, optimize=True)
        rounded(small, 256, 0.15).save(out / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    else:
        for size, name in [(16, "favicon-16.png"), (32, "favicon-32.png")]:
            rounded(src, size, a.radius).save(out / name, optimize=True)
        rounded(src, 256, a.radius).save(out / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])

    # The OS applies its own shape to these: keep them square and opaque.
    src.resize((180, 180), Image.LANCZOS).save(out / "apple-touch-icon.png", optimize=True)
    src.resize((512, 512), Image.LANCZOS).save(out / "icon-512-maskable.png", optimize=True)

    for p in sorted(out.iterdir()):
        if p.suffix in {".png", ".ico"}:
            im = Image.open(p)
            print(f"{p.name}\t{im.size[0]}x{im.size[1]}\t{im.mode}")


if __name__ == "__main__":
    main()
