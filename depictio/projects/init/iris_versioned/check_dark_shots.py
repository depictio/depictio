#!/usr/bin/env python3
"""Are the committed dark screenshots actually dark?

Every docs shot ships as a `_light` / `_dark` pair, and the docs site swaps them
on the theme toggle. A dark capture that silently came out light is invisible in
review — the file exists, the name is right, and nobody opens fourteen PNGs.

Two things go wrong in practice, and neither raises during capture:

* the colour scheme is seeded in `localStorage` before first paint, so a shot
  taken before `MantineProvider` applies it keeps the light chrome;
* Plotly figures are rendered server-side with an explicit `theme` argument, so
  a figure can stay light inside otherwise-dark chrome if that argument is not
  threaded through.

Counts near-white pixels rather than comparing means: a mean hides a white panel
behind a dark surround, which is exactly the failure to catch. A correct dark
shot has essentially none.

    uv run python check_dark_shots.py
    uv run python check_dark_shots.py --root docs/images/v0.12/react
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover - the script is the error message
    print("needs pillow:  uv run --with pillow python check_dark_shots.py")
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_ROOT = REPO_ROOT / "docs" / "images" / "v0.12" / "react"

#: Above this fraction of near-white pixels, a "dark" shot is not dark. Chosen
#: with headroom: the light variants here measure 26-83% and the dark ones 0.0%,
#: so anything in between is a real leak rather than a threshold argument.
MAX_WHITE_PCT = 6.0

#: Downscaled before counting — this is a proportion, and full resolution costs
#: a second per file for no extra signal.
SAMPLE = (360, 225)


def white_fraction(path: Path) -> float:
    img = Image.open(path).convert("RGB").resize(SAMPLE)
    # `tobytes` rather than `getdata`, which Pillow 14 removes. Three bytes per
    # pixel in RGB, so step the flat buffer in threes.
    raw = img.tobytes()
    total = len(raw) // 3
    white = sum(
        1 for i in range(0, len(raw), 3) if raw[i] > 235 and raw[i + 1] > 235 and raw[i + 2] > 235
    )
    return 100.0 * white / total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()

    if not args.root.is_dir():
        print(f"no such directory: {args.root}")
        return 2

    pairs = sorted(args.root.glob("*_dark.png"))
    if not pairs:
        print(f"no *_dark.png under {args.root}")
        return 2

    print(f"{'shot':<40} {'light':>8} {'dark':>8}  verdict")
    failures = []
    for dark in pairs:
        stem = dark.name[: -len("_dark.png")]
        light = dark.with_name(f"{stem}_light.png")
        dark_pct = white_fraction(dark)
        # A missing light counterpart is its own problem: the docs site pairs
        # them by name, so a lone dark shot renders nothing in light mode.
        light_pct = white_fraction(light) if light.is_file() else float("nan")
        ok = dark_pct <= MAX_WHITE_PCT and light.is_file()
        if not ok:
            failures.append(stem)
        print(f"{stem:<40} {light_pct:>8.1f} {dark_pct:>8.1f}  {'ok' if ok else 'FAIL'}")

    print()
    if failures:
        print(f"{len(failures)} shot(s) failed: {', '.join(failures)}")
        print("re-capture with --theme dark, and check the figure theme is threaded through")
        return 1
    print(f"all {len(pairs)} dark shots are dark, and each has a light counterpart")
    return 0


if __name__ == "__main__":
    sys.exit(main())
