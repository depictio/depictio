#!/usr/bin/env python3
"""Screenshot the external site, one delivery mode per shot.

Uses the locally installed Chrome in headless mode with software WebGL, because
several advanced-viz renderers (volcano, embedding, coverage) draw with
scattergl and would otherwise capture as "WebGL is not supported".

    python shoot_site.py [--port 8899] [--modes live file spec]
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent / "screenshots"

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]


def find_chrome() -> str:
    for candidate in CHROME_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    found = shutil.which("google-chrome") or shutil.which("chromium")
    if found:
        return found
    raise SystemExit("No Chrome/Chromium found; install one or screenshot by hand.")


def shoot(chrome: str, url: str, out: Path, height: int, budget_ms: int) -> None:
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
            f"--window-size=1500,{height}",
            f"--virtual-time-budget={budget_ms}",
            f"--screenshot={out}",
            url,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    size = out.stat().st_size if out.exists() else 0
    print(f"  {out.name:28} {size / 1024:8.0f} KB")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8899)
    parser.add_argument("--modes", nargs="*", default=["live", "file", "spec"])
    parser.add_argument(
        "--limit",
        type=int,
        default=6,
        help="cards per shot; each live/file embed is ~7 MB, so all 24 at once hangs headless Chrome",
    )
    parser.add_argument("--budget", type=int, default=40000)
    args = parser.parse_args()

    chrome = find_chrome()
    base = f"http://localhost:{args.port}/"
    print(f"chrome  {chrome}\nsite    {base}\nout     {OUT_DIR}\n")

    shoot(chrome, f"{base}?limit=3", OUT_DIR / "site-top.png", 2600, args.budget)
    height = 900 + 620 * ((args.limit + 1) // 2)
    for mode in args.modes:
        shoot(
            chrome,
            f"{base}?mode={mode}&limit={args.limit}",
            OUT_DIR / f"site-{mode}.png",
            height,
            args.budget,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
