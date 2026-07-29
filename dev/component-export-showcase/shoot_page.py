#!/usr/bin/env python3
"""Screenshot one page at a time, for checking a specific page's rendering.

`shoot_site.py` sweeps the gallery's delivery modes. This one takes a route and
a height, which is what you want when iterating on a single page's styling.

    python shoot_page.py report --height 3400
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from shoot_site import find_chrome

OUT_DIR = Path(__file__).resolve().parent / "screenshots"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("route")
    parser.add_argument("--port", type=int, default=8899)
    parser.add_argument("--height", type=int, default=2400)
    parser.add_argument("--budget", type=int, default=45000)
    parser.add_argument("--name", default=None)
    args = parser.parse_args()

    chrome = find_chrome()
    route = args.route if args.route.startswith("/") else f"/{args.route}"
    url = f"http://localhost:{args.port}{route}"
    out = OUT_DIR / f"{args.name or route.strip('/') or 'index'}.png"
    out.parent.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        [
            chrome,
            "--headless=new",
            "--use-gl=angle",
            "--use-angle=swiftshader",
            "--enable-unsafe-swiftshader",
            "--disable-gpu-sandbox",
            "--hide-scrollbars",
            f"--window-size=1500,{args.height}",
            f"--virtual-time-budget={args.budget}",
            f"--screenshot={out}",
            url,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    size = out.stat().st_size if out.exists() else 0
    print(f"{url} -> {out}  ({size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
