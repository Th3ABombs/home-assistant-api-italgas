"""Genera le immagini brand dell'integrazione (icona originale, non il logo Italgas).

Uso: .venv/bin/python scripts/make_brand.py
Output: custom_components/italgas/brand/icon.png (256) e icon@2x.png (512)
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "custom_components" / "italgas" / "brand"
S = 2048  # disegno ad alta risoluzione, poi ridimensiono (antialiasing)

TOP = (30, 136, 229)  # blu chiaro
BOTTOM = (10, 61, 145)  # blu scuro
INNER = (125, 211, 252)  # azzurro fiamma interna


def bezier(p0, p1, p2, p3, n=60):
    pts = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        pts.append(
            (
                u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
                u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1],
            )
        )
    return pts


def path(start, segments):
    pts, cur = [], start
    for c1, c2, end in segments:
        pts += bezier(cur, c1, c2, end)
        cur = end
    return [(x * S, y * S) for x, y in pts]


OUTER = path(
    (0.53, 0.13),
    [
        ((0.60, 0.30), (0.78, 0.40), (0.78, 0.60)),
        ((0.78, 0.76), (0.65, 0.87), (0.50, 0.87)),
        ((0.35, 0.87), (0.22, 0.76), (0.22, 0.60)),
        ((0.22, 0.48), (0.29, 0.40), (0.35, 0.33)),
        ((0.36, 0.41), (0.40, 0.46), (0.45, 0.48)),
        ((0.43, 0.36), (0.46, 0.22), (0.53, 0.13)),
    ],
)

INNER_FLAME = path(
    (0.51, 0.47),
    [
        ((0.55, 0.56), (0.65, 0.61), (0.65, 0.71)),
        ((0.65, 0.79), (0.58, 0.84), (0.50, 0.84)),
        ((0.42, 0.84), (0.35, 0.79), (0.35, 0.71)),
        ((0.35, 0.63), (0.41, 0.58), (0.44, 0.53)),
        ((0.46, 0.58), (0.48, 0.60), (0.50, 0.61)),
        ((0.49, 0.56), (0.49, 0.52), (0.51, 0.47)),
    ],
)


def make() -> Image.Image:
    # sfondo: quadrato arrotondato con gradiente verticale
    grad = Image.new("RGB", (S, S))
    gd = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / (S - 1)
        gd.line([(0, y), (S, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(TOP, BOTTOM)))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.22), fill=255)
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)

    # ombra morbida della fiamma
    shadow = Image.new("L", (S, S), 0)
    ImageDraw.Draw(shadow).polygon([(x, y + S * 0.015) for x, y in OUTER], fill=90)
    shadow = shadow.filter(ImageFilter.GaussianBlur(S * 0.02))
    img.paste((5, 30, 80, 255), (0, 0), Image.composite(shadow, Image.new("L", (S, S), 0), mask))

    d = ImageDraw.Draw(img)
    d.polygon(OUTER, fill=(255, 255, 255, 255))
    d.polygon(INNER_FLAME, fill=INNER + (255,))
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    big = make()
    for name, size in (("icon.png", 256), ("icon@2x.png", 512)):
        big.resize((size, size), Image.LANCZOS).save(OUT / name, optimize=True)
        print("scritto", OUT / name)


if __name__ == "__main__":
    main()
