#!/usr/bin/env python3
"""Generate the depictio Slack emoji pack from the favicon.

In the spirit of the nf-core / Nextflow Slack (:nextflow-party:, :nf-core-spin:, ...),
this renders the depictio rosette as a set of custom emojis, animated or not, written
to docs/images/slack-emojis/. The emojis are regenerated from the favicon rather than
drawn by hand, so a logo change is one command away.

Run from the repository root (it needs Pillow and NumPy):

    uvx --with pillow --with numpy python scripts/generate_slack_emojis.py

Options:
    --source PATH   The logo PNG (default docs/images/favicon.png).
    --output DIR    Where to write the emojis (default docs/images/slack-emojis).
    --size PX       Emoji side in pixels (default 128, Slack's recommended size).
    --parrot SRC    The party parrot GIF to remix for :depictio-parrot:, a path or URL
                    (default: downloaded from cultofthepartyparrot.com).

How it works:
    1. Every opaque source pixel is given to the nearest of the logo's eight flat
       colours, which splits the rosette into its eight petals: one layer each, so
       animations can move petals independently.
    2. Each frame is composed at 4x on a square canvas centred on the rosette's hub
       (the point its gutters meet at), then downsampled: rotations turn around the
       hub instead of the bounding-box centre, which is off to one side.
    3. GIF has 1-bit transparency, so a pixel is kept when at least half covered, in
       its un-blended petal colour: no halo against either Slack theme.
"""

from __future__ import annotations

import argparse
import colorsys
import io
import math
import random
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageSequence

# The logo's petal colours, clockwise from 12 o'clock (see animated_favicon.svg).
PETALS = {
    "violet": (0x7D, 0x5D, 0xEC),
    "blue": (0x62, 0x79, 0xF0),
    "orange": (0xEE, 0x96, 0x44),
    "yellow": (0xF1, 0xC5, 0x47),
    "green": (0xA1, 0xD4, 0x4D),
    "cyan": (0x58, 0xB3, 0xCB),
    "pink": (0xDC, 0x6E, 0x94),
    "purple": (0xC0, 0x64, 0xD3),
}

# Where the gutters between petals meet, in favicon.png pixels.
HUB = (470, 470)
# Canvas half-width around the hub: the farthest petal tip is ~470 px out.
RADIUS = 480
SUPERSAMPLE = 4
# The standard party parrot, remixed for :depictio-parrot: (not vendored in the repo).
PARROT_URL = "https://cultofthepartyparrot.com/parrots/hd/parrot.gif"
FRAME_MS = 40


def load_petals(source: Path) -> list[Image.Image]:
    """Split the logo into one RGBA layer per petal, on a square canvas around the hub."""
    rgba = np.asarray(Image.open(source).convert("RGBA")).astype(np.int32)
    palette = np.array(list(PETALS.values()), dtype=np.int32)
    dist = ((rgba[..., None, :3] - palette[None, None]) ** 2).sum(-1)
    nearest = dist.argmin(-1)

    side = 2 * RADIUS
    ox, oy = RADIUS - HUB[0], RADIUS - HUB[1]
    h, w = nearest.shape
    layers = []
    for i in range(len(palette)):
        layer = np.zeros((side, side, 4), dtype=np.uint8)
        alpha = np.where(nearest == i, rgba[..., 3], 0).astype(np.uint8)
        layer[oy : oy + h, ox : ox + w, :3] = palette[i]
        layer[oy : oy + h, ox : ox + w, 3] = alpha
        layers.append(Image.fromarray(layer, "RGBA"))
    return layers


def compose(
    layers: list[Image.Image],
    size: int,
    *,
    angle: float = 0.0,
    scale: float = 1.0,
    sx: float = 1.0,
    sy: float = 1.0,
    dx: float = 0.0,
    dy: float = 0.0,
    petal_offsets: list[float] | None = None,
    petal_alpha: list[float] | None = None,
    hue: float = 0.0,
    recolor: list[tuple[int, int, int]] | None = None,
) -> Image.Image:
    """One frame: transforms are in fractions of the emoji side, angles in degrees clockwise."""
    big = size * SUPERSAMPLE
    canvas = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    n = len(layers)
    for i, layer in enumerate(layers):
        if petal_alpha is not None and petal_alpha[i] <= 0:
            continue
        petal = layer
        if recolor is not None or hue:
            arr = np.asarray(petal).copy()
            r, g, b = recolor[i] if recolor is not None else arr[arr[..., 3] > 0][0, :3]
            if hue:
                hh, ll, ss = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
                r, g, b = (round(c * 255) for c in colorsys.hls_to_rgb((hh + hue) % 1, ll, ss))
            arr[..., :3] = (r, g, b)
            petal = Image.fromarray(arr, "RGBA")
        if petal_alpha is not None and petal_alpha[i] < 1:
            arr = np.asarray(petal).copy()
            arr[..., 3] = (arr[..., 3] * petal_alpha[i]).astype(np.uint8)
            petal = Image.fromarray(arr, "RGBA")

        # Base fit: the canvas square maps onto the emoji, then the frame's own transform.
        fit = big / layer.width * scale
        w = max(1, round(layer.width * fit * sx))
        h = max(1, round(layer.height * fit * sy))
        petal = petal.resize((w, h), Image.Resampling.LANCZOS)
        if angle:
            petal = petal.rotate(-angle, resample=Image.Resampling.BICUBIC, expand=True)
        cx = big / 2 + dx * big
        cy = big / 2 + dy * big
        if petal_offsets is not None and petal_offsets[i]:
            # Push the petal outward along its own bisector (petal i spans i*45..(i+1)*45 deg).
            theta = math.radians((i + 0.5) * 360 / n + angle)
            cx += math.sin(theta) * petal_offsets[i] * big
            cy -= math.cos(theta) * petal_offsets[i] * big
        canvas.alpha_composite(petal, (round(cx - petal.width / 2), round(cy - petal.height / 2)))
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


def to_gif_frame(frame: Image.Image) -> Image.Image:
    """Quantize one RGBA frame to a palette image whose index 255 is transparent."""
    arr = np.asarray(frame)
    opaque = arr[..., 3] >= 128
    rgb = Image.fromarray(arr[..., :3], "RGB").quantize(colors=255, method=Image.Quantize.MEDIANCUT)
    idx = np.asarray(rgb).copy()
    idx[~opaque] = 255
    out = Image.fromarray(idx, "P")
    pal = rgb.getpalette()[: 255 * 3]
    out.putpalette(pal + [0] * (768 - len(pal)))
    out.info["transparency"] = 255
    return out


def save_gif(frames: list[Image.Image], path: Path, durations: int | list[int] = FRAME_MS) -> None:
    gif_frames = [to_gif_frame(f) for f in frames]
    gif_frames[0].save(
        path,
        save_all=True,
        append_images=gif_frames[1:],
        duration=durations,
        loop=0,
        disposal=2,
        transparency=255,
        optimize=False,
    )


def ease(t: float) -> float:
    return 0.5 - 0.5 * math.cos(math.pi * t)


# --- the pack ---------------------------------------------------------------------


def spin(layers, size, n=32):
    return [compose(layers, size, angle=360 * k / n, scale=0.98) for k in range(n)]


def fast_spin(layers, size, n=12):
    return [compose(layers, size, angle=360 * k / n, scale=0.98) for k in range(n)]


def party(layers, size, n=24):
    # Party-parrot style: colours cycle through the rainbow while the rosette bobs.
    return [
        compose(
            layers,
            size,
            hue=k / n,
            scale=0.9,
            dx=0.04 * math.sin(2 * math.pi * k / n),
            dy=-0.04 * abs(math.sin(2 * math.pi * k / n)),
            angle=10 * math.sin(2 * math.pi * k / n),
        )
        for k in range(n)
    ]


def bounce(layers, size, n=24):
    frames = []
    for k in range(n):
        t = k / n
        height = abs(math.sin(math.pi * t))  # 0 at contact, 1 at apex
        squash = max(0.0, 1 - height / 0.25)  # squash only near the ground
        frames.append(
            compose(
                layers,
                size,
                scale=0.78,
                sx=1 + 0.12 * squash,
                sy=1 - 0.12 * squash,
                dy=0.08 - 0.18 * height + 0.02 * squash,
            )
        )
    return frames


def intensifies(layers, size, n=16):
    rng = random.Random(42)
    return [
        compose(layers, size, scale=0.9, dx=rng.uniform(-0.05, 0.05), dy=rng.uniform(-0.05, 0.05))
        for _ in range(n)
    ]


def loading(layers, size):
    # Petals light up one by one clockwise, hold, then all fade out together.
    n = len(layers)
    frames, durations = [], []
    for shown in range(n + 1):
        frames.append(
            compose(layers, size, scale=0.98, petal_alpha=[1 if i < shown else 0 for i in range(n)])
        )
        durations.append(120)
    durations[-1] = 600
    for k in range(1, 5):
        frames.append(compose(layers, size, scale=0.98, petal_alpha=[1 - k / 5] * n))
        durations.append(60)
    return frames, durations


def pulse(layers, size):
    # Heartbeat: lub-dub, then rest.
    beats = [1.0, 1.08, 1.16, 1.08, 1.0, 1.06, 1.12, 1.06, 1.0]
    frames = [compose(layers, size, scale=0.84 * s) for s in beats]
    return frames, [50] * (len(beats) - 1) + [500]


def bloom(layers, size, n=28):
    # The petals drift out from the hub and snap back together.
    frames = []
    for k in range(n):
        t = ease(k / (n - 1) * 2) if k < n / 2 else ease(2 - k / (n - 1) * 2)
        frames.append(compose(layers, size, scale=0.8, petal_offsets=[0.08 * t] * len(layers)))
    return frames


def fetch_parrot(source: str) -> Image.Image:
    """The standard party parrot: a local file, or downloaded from the Cult of the Party Parrot."""
    if source.startswith(("http://", "https://")):
        # The site turns away urllib's default user agent.
        req = urllib.request.Request(source, headers={"User-Agent": "curl/8"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return Image.open(io.BytesIO(resp.read()))
    return Image.open(source)


def parrot(layers, size, sprite: Image.Image):
    """The party parrot in depictio colours, a spinning rosette for a hat.

    Each frame's flat body colour is swapped for a colour walked along the petal palette
    (outline and beak untouched), and the hat follows the top of the head.
    """
    frames = [f.convert("RGBA") for f in ImageSequence.Iterator(sprite)]
    durations = [f.info.get("duration", FRAME_MS) for f in ImageSequence.Iterator(sprite)]
    # The petals in hue order make a rainbow that loops, like the original parrot's.
    hls = sorted(colorsys.rgb_to_hls(*(c / 255 for c in rgb)) for rgb in PETALS.values())
    hat = round(size * 0.34)
    out = []
    for k, frame in enumerate(frames):
        frame = frame.resize((size, size), Image.Resampling.NEAREST)
        arr = np.asarray(frame).astype(float)
        opaque = arr[..., 3] > 0
        rgb = arr[..., :3]
        bright = opaque & (rgb.sum(-1) > 300)
        colors, counts = np.unique(rgb[bright].astype(int), axis=0, return_counts=True)
        body = colors[counts.argmax()].astype(float)

        pos = k * len(hls) / len(frames)
        (h0, l0, s0), (h1, l1, s1) = hls[int(pos)], hls[(int(pos) + 1) % len(hls)]
        frac = pos - int(pos)
        dh = (h1 - h0 + 0.5) % 1 - 0.5  # the short way round the hue circle
        target = np.array(
            colorsys.hls_to_rgb((h0 + dh * frac) % 1, l0 + (l1 - l0) * frac, s0 + (s1 - s0) * frac)
        )
        target *= 255
        near = opaque & (np.abs(rgb - body).sum(-1) < 90)
        rgb[near] = np.clip(rgb[near] - body + target, 0, 255)
        frame = Image.fromarray(arr.astype(np.uint8), "RGBA")

        rows = np.nonzero(opaque.any(1))[0]
        top = rows[0]
        head_x = np.nonzero(opaque[top : top + 4].any(0))[0].mean()
        rosette = compose(layers, hat, angle=360 * k / len(frames), scale=0.98)
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        canvas.alpha_composite(frame)
        x = int(np.clip(round(head_x - hat / 2), 0, size - hat))
        y = int(max(0, top - hat * 0.75))
        canvas.alpha_composite(rosette, (x, y))
        out.append(canvas)
    return out, durations


def rose_colors() -> list[tuple[int, int, int]]:
    # Every petal in the pink petal's hue, keeping each petal's own lightness so they stay distinct.
    ph, _, ps = colorsys.rgb_to_hls(*(c / 255 for c in PETALS["pink"]))
    out = []
    for r, g, b in PETALS.values():
        _, ll, _ = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        rr, gg, bb = colorsys.hls_to_rgb(ph, min(0.8, max(0.45, ll)), max(ps, 0.6))
        out.append((round(rr * 255), round(gg * 255), round(bb * 255)))
    return out


def preview_sheet(paths: list[Path], size: int, out: Path) -> None:
    """A light and a dark row of every emoji's first non-blank frame, for the README."""
    pad, label_h = 16, 18
    cols = len(paths)
    cell = size + pad
    sheet = Image.new("RGB", (cols * cell + pad, 2 * (cell + label_h) + pad), "white")
    draw = ImageDraw.Draw(sheet)
    draw.rectangle([0, cell + label_h + pad // 2, sheet.width, sheet.height], fill=(26, 29, 33))
    for row, (text_color, y0) in enumerate(
        (((0, 0, 0), pad), ((230, 230, 230), cell + label_h + pad))
    ):
        for col, path in enumerate(paths):
            im = next(
                f
                for f in (f.convert("RGBA") for f in ImageSequence.Iterator(Image.open(path)))
                if np.asarray(f)[..., 3].any()
            )
            x = pad + col * cell
            sheet.paste(im, (x, y0), im)
            name = path.stem.removeprefix("depictio-") if path.stem != "depictio" else "depictio"
            draw.text((x, y0 + size + 2), name, fill=text_color)
    sheet.save(out)


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, default=root / "docs/images/favicon.png")
    parser.add_argument("--output", type=Path, default=root / "docs/images/slack-emojis")
    parser.add_argument("--size", type=int, default=128)
    parser.add_argument("--parrot", default=PARROT_URL)
    args = parser.parse_args()

    out: Path = args.output
    out.mkdir(parents=True, exist_ok=True)
    size = args.size
    layers = load_petals(args.source)
    rose = rose_colors()

    written: list[Path] = []

    def png(name: str, frame: Image.Image) -> None:
        path = out / f"{name}.png"
        frame.save(path, optimize=True)
        written.append(path)

    def gif(name: str, frames, durations=FRAME_MS) -> None:
        path = out / f"{name}.gif"
        save_gif(frames, path, durations)
        written.append(path)

    png("depictio", compose(layers, size, scale=0.98))
    png("depictio-rose", compose(layers, size, scale=0.98, recolor=rose))
    gif("depictio-spin", spin(layers, size))
    gif("depictio-fast-spin", fast_spin(layers, size))
    gif("depictio-party", party(layers, size))
    gif("depictio-bounce", bounce(layers, size))
    gif("depictio-intensifies", intensifies(layers, size), 30)
    gif("depictio-loading", *loading(layers, size))
    gif("depictio-pulse", *pulse(layers, size))
    gif("depictio-bloom", bloom(layers, size))
    gif("depictio-parrot", *parrot(layers, size, fetch_parrot(args.parrot)))
    gif(
        "depictio-rose-spin",
        [compose(layers, size, angle=360 * k / 32, scale=0.98, recolor=rose) for k in range(32)],
    )

    preview_sheet(written, size, out / "preview.png")
    for path in written:
        kb = path.stat().st_size / 1024
        flag = "  <-- over Slack's 128 KB limit" if kb > 128 else ""
        print(f"{path.relative_to(root)}  {kb:6.1f} KB{flag}")


if __name__ == "__main__":
    main()
