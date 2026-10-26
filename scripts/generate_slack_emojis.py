#!/usr/bin/env python3
"""Generate the depictio Slack emoji pack from the depictio rose.

In the spirit of the nf-core / Nextflow Slack (:nextflow-party:, :nf-core-spin:, ...),
this turns the depictio mark into custom emojis, written to docs/images/slack-emojis/.

Run from the repository root (it needs Pillow, NumPy, Node and Playwright's Chromium,
the same install the e2e suite uses):

    uvx --with pillow --with numpy python scripts/generate_slack_emojis.py

Options:
    --output DIR    Where to write the emojis (default docs/images/slack-emojis).
    --size PX       Emoji side in pixels (default 128, Slack's recommended size).
    --parrot SRC    The party parrot GIF to remix for :depictio-parrot:, a path or URL
                    (default: downloaded from cultofthepartyparrot.com).

Where the frames come from:
    1. The rose animations (loading, fan, pulse, data, sweep, wave, spring, domino) are
       the app's own: scripts/slack_emojis_capture.mjs plays depictio-rose.js, the file
       behind <DepictioRose>, in Chromium and seeks it frame by frame. A change to the
       mark or its motion in the viewer reaches the emojis on the next run.
    2. The classic Slack effects (spin, party, bounce, intensifies, parrot) move the
       still logo, captured the same way, so they share its exact geometry.
    3. Frames are captured at 512 px and downsampled. GIF has 1-bit transparency, so a
       pixel is kept when at least half covered, in its un-blended colour: no halo
       against either Slack theme. Runs of identical frames merge into one, and a GIF
       over Slack's 128 KB limit drops every other frame until it fits.
"""

from __future__ import annotations

import argparse
import colorsys
import io
import json
import math
import random
import subprocess
import tempfile
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageSequence

ROOT = Path(__file__).resolve().parent.parent
CAPTURE = ROOT / "scripts" / "slack_emojis_capture.mjs"
# The standard party parrot, remixed for :depictio-parrot: (not vendored in the repo).
PARROT_URL = "https://cultofthepartyparrot.com/parrots/hd/parrot.gif"
SLACK_LIMIT = 128 * 1024
FRAME_MS = 40

# The rose's own modes. "loop" takes one period of a mode that never rests; "story"
# plays the opening, `loops` periods, then closes back to the disc it opened from.
# The long modes run faster than in the app, so they fit Slack's 128 KB at 20 fps.
ROSE_JOBS = [
    {"name": "depictio-loading", "mode": "loading", "kind": "loop"},
    {"name": "depictio-fan", "mode": "fan", "kind": "loop", "speed": 1.8},
    {"name": "depictio-pulse", "mode": "pulse", "kind": "story", "loops": 2},
    {"name": "depictio-data", "mode": "live", "kind": "story", "loops": 1, "speed": 1.4},
    {"name": "depictio-sweep", "mode": "sweep", "kind": "loop"},
    {"name": "depictio-wave", "mode": "wave", "kind": "story", "loops": 1, "speed": 1.9},
    {"name": "depictio-spring", "mode": "spring", "kind": "loop"},
    {"name": "depictio-domino", "mode": "domino", "kind": "loop"},
]


def capture(jobs: list[dict], workdir: Path) -> dict[str, tuple[list[Image.Image], int]]:
    """Run the Chromium capture; returns each job's RGBA frames and frame duration."""
    jobs_path = workdir / "jobs.json"
    jobs_path.write_text(json.dumps(jobs))
    subprocess.run(["node", str(CAPTURE), str(jobs_path), str(workdir)], check=True)
    out = {}
    for job in jobs:
        meta = json.loads((workdir / job["name"] / "frames.json").read_text())
        out[job["name"]] = (
            [Image.open(p).convert("RGBA") for p in meta["frames"]],
            meta["frame_ms"],
        )
    return out


def to_gif_frame(frame: Image.Image, palette: np.ndarray | None = None) -> Image.Image:
    """Quantize one RGBA frame to a palette image whose index 255 is transparent.

    With `palette` (the rose's wedge colours) every opaque pixel snaps to its nearest
    wedge colour: the wedges are flat and the gaps between them keep edges from ever
    meeting, so nothing is lost, and the flat frames compress several times better.
    """
    arr = np.asarray(frame)
    opaque = arr[..., 3] >= 128
    if palette is None:
        rgb = Image.fromarray(arr[..., :3], "RGB").quantize(
            colors=255, method=Image.Quantize.MEDIANCUT
        )
        idx = np.asarray(rgb).copy()
        pal = rgb.getpalette()[: 255 * 3]
    else:
        dist = ((arr[..., None, :3].astype(int) - palette[None, None].astype(int)) ** 2).sum(-1)
        idx = dist.argmin(-1).astype(np.uint8)
        pal = palette.astype(int).flatten().tolist()
    idx[~opaque] = 255
    out = Image.fromarray(idx, "P")
    out.putpalette(pal + [0] * (768 - len(pal)))
    out.info["transparency"] = 255
    return out


def save_gif(
    frames: list[Image.Image],
    path: Path,
    durations: int | list[int] = FRAME_MS,
    palette: np.ndarray | None = None,
) -> None:
    gif = [to_gif_frame(f, palette) for f in frames]
    ms = durations if isinstance(durations, list) else [durations] * len(gif)

    # A rose at rest holds the same picture for many frames: one frame, held longer.
    merged, merged_ms = [gif[0]], [ms[0]]
    for frame, d in zip(gif[1:], ms[1:]):
        if np.array_equal(np.asarray(frame), np.asarray(merged[-1])):
            merged_ms[-1] += d
        else:
            merged.append(frame)
            merged_ms.append(d)

    while True:
        merged[0].save(
            path,
            save_all=True,
            append_images=merged[1:],
            duration=merged_ms,
            loop=0,
            disposal=2,
            transparency=255,
        )
        if path.stat().st_size <= SLACK_LIMIT or len(merged) < 8:
            return
        # Too big for Slack: half the frames, each shown twice as long.
        merged_ms = [a + b for a, b in zip(merged_ms[::2], merged_ms[1::2] + [0])]
        merged = merged[::2]


def fit(
    frame: Image.Image,
    size: int,
    scale: float = 1.0,
    angle: float = 0.0,
    dx: float = 0.0,
    dy: float = 0.0,
    sx: float = 1.0,
    sy: float = 1.0,
) -> Image.Image:
    """Place the 512 px still on a size x size emoji: scale, rotation (degrees clockwise),
    offset (fractions of the side), and squash."""
    big = frame.width
    im = frame.rotate(-angle, resample=Image.Resampling.BICUBIC) if angle else frame
    w, h = max(1, round(big * scale * sx)), max(1, round(big * scale * sy))
    im = im.resize((w, h), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    canvas.alpha_composite(im, (round((big - w) / 2 + dx * big), round((big - h) / 2 + dy * big)))
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


# --- classic Slack effects on the still logo ----------------------------------------


def spin(still, size, n=32):
    return [fit(still, size, angle=360 * k / n) for k in range(n)]


def fast_spin(still, size, n=12):
    return [fit(still, size, angle=360 * k / n) for k in range(n)]


def shift_colors(still: Image.Image, wedges: np.ndarray, step: int) -> Image.Image:
    """Every wedge takes the colour `step` places further round the rainbow."""
    arr = np.asarray(still).copy()
    order = np.argsort([colorsys.rgb_to_hls(*(v / 255 for v in c))[0] for c in wedges])
    nxt = np.empty(len(wedges), dtype=int)
    nxt[order] = order[(np.arange(len(wedges)) + step) % len(wedges)]
    dist = ((arr[..., None, :3].astype(int) - wedges[None, None].astype(int)) ** 2).sum(-1)
    arr[..., :3] = wedges[nxt[dist.argmin(-1)]]
    return Image.fromarray(arr, "RGBA")


def party(still, size, wedges, n=24):
    # Party-parrot style: the wedge colours rotate round the rainbow while the rose bobs.
    per_color = n // len(wedges)
    return [
        fit(
            shift_colors(still, wedges, k // per_color),
            size,
            scale=0.9,
            angle=10 * math.sin(2 * math.pi * k / n),
            dx=0.04 * math.sin(2 * math.pi * k / n),
            dy=-0.04 * abs(math.sin(2 * math.pi * k / n)),
        )
        for k in range(n)
    ]


def bounce(still, size, n=24):
    frames = []
    for k in range(n):
        height = abs(math.sin(math.pi * k / n))  # 0 at contact, 1 at apex
        squash = max(0.0, 1 - height / 0.25)  # squash only near the ground
        frames.append(
            fit(
                still,
                size,
                scale=0.78,
                sx=1 + 0.12 * squash,
                sy=1 - 0.12 * squash,
                dy=0.08 - 0.18 * height + 0.02 * squash,
            )
        )
    return frames


def intensifies(still, size, n=16):
    rng = random.Random(42)
    return [
        fit(still, size, scale=0.9, dx=rng.uniform(-0.05, 0.05), dy=rng.uniform(-0.05, 0.05))
        for _ in range(n)
    ]


def fetch_parrot(source: str) -> Image.Image:
    """The standard party parrot: a local file, or downloaded from the Cult of the Party Parrot."""
    if source.startswith(("http://", "https://")):
        # The site turns away urllib's default user agent.
        req = urllib.request.Request(source, headers={"User-Agent": "curl/8"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return Image.open(io.BytesIO(resp.read()))
    return Image.open(source)


def wedge_colors(still: Image.Image) -> np.ndarray:
    """The rose's eight flat wedge colours, read from the captured still."""
    arr = np.asarray(still)
    colors, counts = np.unique(arr[arr[..., 3] == 255][:, :3], axis=0, return_counts=True)
    return colors[counts > 0.02 * counts.sum()]


def wedge_hls(still: Image.Image) -> list[tuple[float, float, float]]:
    """The rose's wedge colours as HLS, in hue order: a rainbow that loops."""
    return sorted(colorsys.rgb_to_hls(*(v / 255 for v in c)) for c in wedge_colors(still))


def parrot(still, size, sprite: Image.Image):
    """The party parrot in depictio colours, a spinning rose for a hat.

    Each frame's flat body colour is swapped for a colour walked along the rose's
    palette (outline and beak untouched), and the hat follows the top of the head.
    """
    frames = [f.convert("RGBA") for f in ImageSequence.Iterator(sprite)]
    durations = [f.info.get("duration", FRAME_MS) for f in ImageSequence.Iterator(sprite)]
    hls = wedge_hls(still)
    hat = round(size * 0.34)
    out = []
    for k, frame in enumerate(frames):
        frame = frame.resize((size, size), Image.Resampling.NEAREST)
        px = np.asarray(frame).astype(float)
        opaque = px[..., 3] > 0
        rgb = px[..., :3]
        bright = opaque & (rgb.sum(-1) > 300)
        colors, n = np.unique(rgb[bright].astype(int), axis=0, return_counts=True)
        body = colors[n.argmax()].astype(float)

        pos = k * len(hls) / len(frames)
        (h0, l0, s0), (h1, l1, s1) = hls[int(pos)], hls[(int(pos) + 1) % len(hls)]
        frac = pos - int(pos)
        dh = (h1 - h0 + 0.5) % 1 - 0.5  # the short way round the hue circle
        target = 255 * np.array(
            colorsys.hls_to_rgb((h0 + dh * frac) % 1, l0 + (l1 - l0) * frac, s0 + (s1 - s0) * frac)
        )
        near = opaque & (np.abs(rgb - body).sum(-1) < 90)
        rgb[near] = np.clip(rgb[near] - body + target, 0, 255)
        frame = Image.fromarray(px.astype(np.uint8), "RGBA")

        top = np.nonzero(opaque.any(1))[0][0]
        head_x = np.nonzero(opaque[top : top + 4].any(0))[0].mean()
        rose = fit(still, hat, angle=360 * k / len(frames))
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        canvas.alpha_composite(frame)
        x = int(np.clip(round(head_x - hat / 2), 0, size - hat))
        canvas.alpha_composite(rose, (x, int(max(0, top - hat * 0.75))))
        out.append(canvas)
    return out, durations


def preview_sheet(paths: list[Path], size: int, out: Path) -> None:
    """A light and a dark row of every emoji's resting frame, for the README."""
    pad, label_h = 16, 18
    cell = size + pad
    sheet = Image.new("RGB", (len(paths) * cell + pad, 2 * (cell + label_h) + pad), "white")
    draw = ImageDraw.Draw(sheet)
    draw.rectangle([0, cell + label_h + pad // 2, sheet.width, sheet.height], fill=(26, 29, 33))
    for text_color, y0 in (((0, 0, 0), pad), ((230, 230, 230), cell + label_h + pad)):
        for col, path in enumerate(paths):
            frames = [f.convert("RGBA") for f in ImageSequence.Iterator(Image.open(path))]
            # The frame held longest is where the animation rests: usually the logo.
            im = (
                max(frames, key=lambda f: f.info.get("duration", 0))
                if len(frames) > 1
                else frames[0]
            )
            x = pad + col * cell
            sheet.paste(im, (x, y0), im)
            name = path.stem.removeprefix("depictio-") if path.stem != "depictio" else "depictio"
            draw.text((x, y0 + size + 2), name, fill=text_color)
    sheet.save(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=ROOT / "docs/images/slack-emojis")
    parser.add_argument("--size", type=int, default=128)
    parser.add_argument("--parrot", default=PARROT_URL)
    args = parser.parse_args()

    out: Path = args.output
    out.mkdir(parents=True, exist_ok=True)
    size = args.size

    with tempfile.TemporaryDirectory() as tmp:
        jobs = [{"name": "still", "mode": "logo", "kind": "still"}]
        jobs += [{"fps": 20, **job} for job in ROSE_JOBS]
        captured = capture(jobs, Path(tmp))
    still = captured.pop("still")[0][0]

    written: list[Path] = []

    def gif(name: str, frames, durations=FRAME_MS, palette=None) -> None:
        path = out / f"{name}.gif"
        save_gif(frames, path, durations, palette)
        written.append(path)

    wedges = wedge_colors(still)
    assert len(wedges) == 8, f"expected the rose's 8 wedge colours, found {len(wedges)}"

    path = out / "depictio.png"
    fit(still, size).save(path, optimize=True)
    written.append(path)
    for job in ROSE_JOBS:
        frames, ms = captured[job["name"]]
        gif(
            job["name"],
            [f.resize((size, size), Image.Resampling.LANCZOS) for f in frames],
            ms,
            wedges,
        )
    gif("depictio-spin", spin(still, size), palette=wedges)
    gif("depictio-fast-spin", fast_spin(still, size), palette=wedges)
    gif("depictio-party", party(still, size, wedges), palette=wedges)
    gif("depictio-bounce", bounce(still, size), palette=wedges)
    gif("depictio-intensifies", intensifies(still, size), 30, wedges)
    gif("depictio-parrot", *parrot(still, size, fetch_parrot(args.parrot)))

    preview_sheet(written, size, out / "preview.png")
    for path in written:
        print(f"{path.relative_to(ROOT)}  {path.stat().st_size / 1024:6.1f} KB")


if __name__ == "__main__":
    main()
