#!/usr/bin/env python3
"""Generate the depictio logo the CLI draws on its landing screen.

`depictio` with no command prints the logo in block characters beside its name. The
pixels come from depictio/cli/cli/utils/logo_art.py, which this script writes from the
logo image, so the art is regenerated rather than redrawn by hand.

Run from the repository root, in the dev environment (it needs Pillow and NumPy):

    .venv/bin/python scripts/generate_cli_logo.py

or without one:

    uvx --with pillow --with numpy python scripts/generate_cli_logo.py

Options:
    --source PATH          The logo: any image Pillow opens, or an SVG wrapping one.
                           The default, the web app's favicon.svg, is such a wrapper: an
                           embedded PNG under an auto-traced layer whose stray specks we
                           skip. No SVG rasterizer is needed.
    --size NAME=COLSxROWS  A rendition and the terminal cells it may fill (repeatable).
    --glyphs half|quadrant Half blocks (1x2 pixels a cell) or quadrants (2x2).
    --cell-aspect RATIO    A terminal cell's height over its width.
    --output PATH          The module to write.
    --preview              Print the renditions in this terminal instead.

How a rendition is made:
    1. The palette is the logo's own flat colours, read from its opaque pixels.
    2. Each source pixel is given to the nearest palette colour, weighted by its alpha,
       and every terminal pixel takes the exact area average of those masks over its
       footprint: supersampling, with the ~800 px source as the samples.
    3. The grid is fitted to the logo: among scales of 90-100% and sub-pixel offsets,
       the one leaving the fewest half-covered pixels wins, so the straight gutters
       between the wedges land on pixel boundaries instead of smearing.
    4. A pixel is drawn when at least half covered, in the colour covering most of it.
       Edge pixels are never blended toward a background: the terminal's is unknown.
    5. With quadrants a cell shows two colours at most, the terminal background being
       one of them wherever the cell is partly transparent; each cell takes the pair
       that keeps the most coverage.
"""

from __future__ import annotations

import argparse
import base64
import html
import itertools
import re
import shlex
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = "depictio/viewer/public/favicon.svg"
DEFAULT_OUTPUT = "depictio/cli/cli/utils/logo_art.py"
DEFAULT_SIZES = ("large=23x12", "compact=18x9")
TRANSPARENT = "."
# Pixels per cell, across and down.
CELL_PIXELS = {"half": (1, 2), "quadrant": (2, 2)}
# Block characters by the quarters they fill: top-left, top-right, bottom-left,
# bottom-right. Half blocks are the subset whose columns match.
QUADRANT_GLYPHS = {
    (0, 0, 0, 0): " ",
    (1, 0, 0, 0): "▘",
    (0, 1, 0, 0): "▝",
    (0, 0, 1, 0): "▖",
    (0, 0, 0, 1): "▗",
    (1, 1, 0, 0): "▀",
    (0, 0, 1, 1): "▄",
    (1, 0, 1, 0): "▌",
    (0, 1, 0, 1): "▐",
    (1, 0, 0, 1): "▚",
    (0, 1, 1, 0): "▞",
    (1, 1, 1, 0): "▛",
    (1, 1, 0, 1): "▜",
    (1, 0, 1, 1): "▙",
    (0, 1, 1, 1): "▟",
    (1, 1, 1, 1): "█",
}


def load_source(path: Path) -> Image.Image:
    """The logo as RGBA, with a transparent margin for the grid to slide into."""
    if path.suffix.lower() == ".svg":
        match = re.search(r'href="data:image/\w+;base64,([^"]+)"', path.read_text())
        if not match:
            sys.exit(f"{path} embeds no raster image: export it to PNG and pass that.")
        data = base64.b64decode(re.sub(r"\s", "", html.unescape(match.group(1))))
        from io import BytesIO

        image = Image.open(BytesIO(data))
    else:
        image = Image.open(path)
    image = image.convert("RGBA")
    margin = max(image.size) // 4
    padded = Image.new("RGBA", (image.width + 2 * margin, image.height + 2 * margin))
    padded.paste(image, (margin, margin))
    return padded


def extract_palette(pixels: np.ndarray, min_share=0.002, min_distance=40) -> np.ndarray:
    """The logo's flat colours: the commonest opaque colours, merging near duplicates."""
    opaque = pixels[pixels[..., 3] == 255][:, :3]
    colours, counts = np.unique(opaque, axis=0, return_counts=True)
    palette: list[np.ndarray] = []
    for i in np.argsort(-counts):
        if counts[i] < min_share * len(opaque):
            break
        colour = colours[i].astype(int)
        if all(np.linalg.norm(colour - p) > min_distance for p in palette):
            palette.append(colour)
    return np.array(palette)


def summed_area_tables(pixels: np.ndarray, palette: np.ndarray) -> np.ndarray:
    """Per palette colour, the summed-area table of its alpha-weighted mask."""
    distances = ((pixels[..., None, :3].astype(float) - palette[None, None]) ** 2).sum(-1)
    nearest = distances.argmin(-1)
    alpha = pixels[..., 3] / 255
    height, width = nearest.shape
    tables = np.zeros((len(palette), height + 1, width + 1))
    for k in range(len(palette)):
        tables[k, 1:, 1:] = ((nearest == k) * alpha).cumsum(0).cumsum(1)
    return tables


def coverage(tables, left, top, step_x, step_y, width, height) -> np.ndarray:
    """Exact area average of each colour over a width x height grid of pixels.

    The integral of a piecewise-constant image is bilinear between the corners of the
    summed-area table, so interpolating the table gives exact sums over boxes with
    fractional edges.
    """
    xs = np.clip(left + step_x * np.arange(width + 1), 0, tables.shape[2] - 1)
    ys = np.clip(top + step_y * np.arange(height + 1), 0, tables.shape[1] - 1)
    x0 = np.minimum(xs.astype(int), tables.shape[2] - 2)
    y0 = np.minimum(ys.astype(int), tables.shape[1] - 2)
    fx, fy = (xs - x0)[None, :], (ys - y0)[:, None]
    y0, x0 = y0[:, None], x0[None, :]
    integral = (
        tables[:, y0, x0] * (1 - fy) * (1 - fx)
        + tables[:, y0, x0 + 1] * (1 - fy) * fx
        + tables[:, y0 + 1, x0] * fy * (1 - fx)
        + tables[:, y0 + 1, x0 + 1] * fy * fx
    )
    boxes = (
        integral[:, 1:, 1:] - integral[:, :-1, 1:] - integral[:, 1:, :-1] + integral[:, :-1, :-1]
    )
    return np.moveaxis(boxes / (step_x * step_y), 0, -1)


def ambiguity(cov: np.ndarray) -> float:
    """How many pixels sit on an edge: half covered, or split between two colours."""
    total = cov.sum(-1)
    runner_up = np.sort(cov, -1)[..., -2]
    return float(np.minimum(total, 1 - total).sum() + runner_up.sum())


def fit_grid(tables, bbox, width, height, pixel_aspect) -> np.ndarray:
    """Coverage on the grid that best fits the logo's edges (see the module docstring)."""
    x0, y0, x1, y1 = bbox
    centre_x, centre_y = (x0 + x1) / 2, (y0 + y1) / 2
    fit = max((x1 - x0) / width, (y1 - y0) / (height * pixel_aspect))
    best = None
    for scale in np.arange(0.90, 1.0001, 0.005):
        step_x = fit * scale
        step_y = step_x * pixel_aspect
        for dx, dy in itertools.product(np.linspace(-0.5, 0.5, 17), repeat=2):
            left = centre_x - step_x * (width / 2 - dx)
            top = centre_y - step_y * (height / 2 - dy)
            cov = coverage(tables, left, top, step_x, step_y, width, height)
            # Per unit of scale, or the smallest logo would always win.
            score = ambiguity(cov) / scale
            if best is None or score < best[0]:
                best = (score, cov)
    return best[1]


def assign_pixels(cov: np.ndarray, across: int, down: int) -> np.ndarray:
    """Each pixel's palette index, or -1 where transparent, at most two per cell."""
    height, width, colours = cov.shape
    # Score of each choice per pixel: transparent first, then each colour.
    scores = np.concatenate([(1 - cov.sum(-1))[..., None], cov], -1)
    pixels = np.empty((height, width), dtype=int)
    for top, left in itertools.product(range(0, height, down), range(0, width, across)):
        cell = scores[top : top + down, left : left + across].reshape(-1, colours + 1)
        best = max(
            itertools.combinations_with_replacement(range(colours + 1), 2),
            key=lambda pair: np.maximum(cell[:, pair[0]], cell[:, pair[1]]).sum(),
        )
        chosen = np.where(cell[:, best[0]] >= cell[:, best[1]], best[0], best[1])
        pixels[top : top + down, left : left + across] = (chosen - 1).reshape(down, across)
    return pixels


def crop_to_cells(cov: np.ndarray, across: int, down: int) -> np.ndarray:
    """Drop empty margins, keeping whole cells."""
    rows, cols = np.nonzero(cov.sum(-1) >= 0.5)
    cov = cov[rows.min() : rows.max() + 1, cols.min() : cols.max() + 1]
    pad_y, pad_x = -cov.shape[0] % down, -cov.shape[1] % across
    # Split any padding so the logo stays centred in its cells.
    return np.pad(
        cov,
        ((pad_y // 2, pad_y - pad_y // 2), (pad_x // 2, pad_x - pad_x // 2), (0, 0)),
    )


def render(image, palette, tables, cols, rows, glyphs, cell_aspect) -> list[str]:
    """One rendition's pixel rows, a letter per palette colour, '.' where transparent."""
    across, down = CELL_PIXELS[glyphs]
    # A pixel's height over its width, the cell being cell_aspect times taller than wide.
    pixel_aspect = cell_aspect * across / down
    alpha = np.asarray(image.getchannel("A"))
    ys, xs = np.nonzero(alpha >= 128)
    bbox = (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)
    cov = fit_grid(tables, bbox, cols * across, rows * down, pixel_aspect)
    pixels = assign_pixels(crop_to_cells(cov, across, down), across, down)
    letters = palette_letters(len(palette))
    return ["".join(TRANSPARENT if p < 0 else letters[p] for p in row) for row in pixels]


def palette_letters(n: int) -> str:
    return "abcdefghijklmnopqrstuvwxyz"[:n]


def cells(pixels: list[str], glyphs: str):
    """Yield rows of (glyph, foreground, background) letters, None being the terminal's
    own colour: the cells the CLI draws (_logo_cell in depictio/cli/depictio_cli.py)."""
    across, _ = CELL_PIXELS[glyphs]
    for upper, lower in zip(pixels[::2], pixels[1::2]):
        row = []
        for x in range(0, len(upper), across):
            quarters = (upper[x], upper[x + across - 1], lower[x], lower[x + across - 1])
            colours = [c for c in dict.fromkeys(quarters) if c != TRANSPARENT]
            lit = tuple(int(q == colours[0]) for q in quarters) if colours else (0, 0, 0, 0)
            if not colours:
                row.append((" ", None, None))
            elif all(lit):
                row.append((" ", None, colours[0]))
            else:
                behind = colours[1] if len(colours) > 1 else None
                row.append((QUADRANT_GLYPHS[lit], colours[0], behind))
        yield row


def preview(renditions: dict, colours: dict[str, str]) -> None:
    def sgr(hex_colour: str, ground: int) -> str:
        r, g, b = (int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))
        return f"\x1b[{ground};2;{r};{g};{b}m"

    for name, (glyphs, pixels) in renditions.items():
        print(f"{name}: {len(pixels[0]) // CELL_PIXELS[glyphs][0]}x{len(pixels) // 2} cells")
        for row in cells(pixels, glyphs):
            line = ""
            for glyph, fg, bg in row:
                style = (sgr(colours[fg], 38) if fg else "") + (sgr(colours[bg], 48) if bg else "")
                line += f"{style}{glyph}\x1b[0m" if style else glyph
            print(line)
        print()


def write_module(path: Path, renditions: dict, colours: dict[str, str], command: str) -> None:
    lines = [
        '"""The depictio logo, as pixels for the CLI landing to draw in block characters.',
        "",
        "Generated by scripts/generate_cli_logo.py: do not edit by hand. Regenerate with",
        "",
        f"    {command}",
        '"""',
        "",
        "# The logo's own colours, by the letter its pixels use.",
        "PALETTE = {",
        *(f'    "{letter}": "{hex_colour}",' for letter, hex_colour in colours.items()),
        "}",
        "",
        "# Each rendition's pixel rows, top to bottom, with '.' where the logo is transparent.",
        '# "half" cells hold 1x2 pixels, "quadrant" cells 2x2; a cell never mixes more than',
        "# two colours, nor a colour with a transparent pixel and a second colour.",
        "LOGOS = {",
    ]
    for name, (glyphs, pixels) in renditions.items():
        lines += [f'    "{name}": {{', f'        "glyphs": "{glyphs}",', '        "pixels": (']
        lines += [f'            "{row}",' for row in pixels]
        lines += ["        ),", "    },"]
    lines += ["}", ""]
    path.write_text("\n".join(lines))


def parse_size(spec: str) -> tuple[str, int, int]:
    match = re.fullmatch(r"(\w+)=(\d+)x(\d+)", spec)
    if not match:
        raise argparse.ArgumentTypeError(f"expected NAME=COLSxROWS, got {spec!r}")
    return match.group(1), int(match.group(2)), int(match.group(3))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source", default=DEFAULT_SOURCE, help="logo image or SVG")
    parser.add_argument(
        "--size",
        action="append",
        type=parse_size,
        help=f"NAME=COLSxROWS, repeatable (default: {' '.join(DEFAULT_SIZES)})",
    )
    parser.add_argument("--glyphs", choices=sorted(CELL_PIXELS), default="half")
    parser.add_argument(
        "--cell-aspect",
        type=float,
        default=2.0,
        help="a terminal cell's height over its width (default: 2.0, square half blocks)",
    )
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="module to write")
    parser.add_argument("--preview", action="store_true", help="print instead of writing")
    args = parser.parse_args()
    sizes = args.size or [parse_size(spec) for spec in DEFAULT_SIZES]

    source = REPO / args.source
    image = load_source(source)
    pixels = np.asarray(image)
    palette = extract_palette(pixels)
    tables = summed_area_tables(pixels, palette)
    colours = {
        letter: "#{:02X}{:02X}{:02X}".format(*colour)
        for letter, colour in zip(palette_letters(len(palette)), palette)
    }
    renditions = {
        name: (
            args.glyphs,
            render(image, palette, tables, cols, rows, args.glyphs, args.cell_aspect),
        )
        for name, cols, rows in sizes
    }

    if args.preview:
        preview(renditions, colours)
        return
    command = [".venv/bin/python", "scripts/generate_cli_logo.py"]
    if args.source != DEFAULT_SOURCE:
        command += ["--source", args.source]
    for name, cols, rows in sizes:
        command += ["--size", f"{name}={cols}x{rows}"]
    if args.glyphs != "half":
        command += ["--glyphs", args.glyphs]
    if args.cell_aspect != 2.0:
        command += ["--cell-aspect", f"{args.cell_aspect:g}"]
    if args.output != DEFAULT_OUTPUT:
        command += ["--output", args.output]
    output = REPO / args.output
    write_module(output, renditions, colours, shlex.join(command))
    for name, (glyphs, rows) in renditions.items():
        across, down = CELL_PIXELS[glyphs]
        print(f"{name}: {len(rows[0]) // across}x{len(rows) // down} cells")
    print(f"wrote {output.relative_to(REPO) if output.is_relative_to(REPO) else output}")


if __name__ == "__main__":
    main()
