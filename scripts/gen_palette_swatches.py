"""Write the palette swatch sheets used by ``docs/design/palettes.md``.

Every colour comes from ``depictio.models.palettes`` (the JSON source), so the
sheets cannot drift from what figures draw. Re-run after editing the palette:

    DEPICTIO_CONTEXT=cli python scripts/gen_palette_swatches.py
"""

from __future__ import annotations

import argparse
from html import escape
from pathlib import Path

from depictio.models import palettes as P
from depictio.models.palettes import cvd

BG = {"light": "#FFFFFF", "dark": "#1A1B1E"}
FONT = "font-family='Inter, -apple-system, Segoe UI, Roboto, sans-serif'"
SW = 34  # swatch size


def _text(
    x: float,
    y: float,
    s: str,
    size: int = 12,
    fill: str = "#343A40",
    weight: int = 400,
    anchor: str = "start",
) -> str:
    return (
        f"<text x='{x}' y='{y}' {FONT} font-size='{size}' font-weight='{weight}' "
        f"fill='{fill}' text-anchor='{anchor}'>{escape(s)}</text>"
    )


def _rect(x: float, y: float, w: float, h: float, fill: str, rx: int = 4, stroke: str = "") -> str:
    extra = f" stroke='{stroke}'" if stroke else ""
    return f"<rect x='{x}' y='{y}' width='{w}' height='{h}' rx='{rx}' fill='{fill}'{extra}/>"


def _svg(width: int, height: int, body: list[str]) -> str:
    return (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' "
        f"viewBox='0 0 {width} {height}'>{_rect(0, 0, width, height, '#FFFFFF', 0)}"
        + "".join(body)
        + "</svg>\n"
    )


def _ramp(x: float, y: float, colours: list[str], w: float, h: float = 14) -> list[str]:
    step = w / len(colours)
    return [_rect(x + i * step, y, step + 0.5, h, c, 0) for i, c in enumerate(colours)]


def palettes_sheet() -> str:
    """Six palettes: categorical slots and ramps, each mode on its own surface."""
    body: list[str] = []
    row_h, top = 150, 40
    body.append(
        _text(
            16,
            24,
            "depictio plot palettes (8 categorical slots, sequential and "
            "diverging ramps), light and dark",
            14,
            weight=600,
        )
    )
    for r, pid in enumerate(P.palette_ids()):
        y0 = top + r * row_h
        label = P.palette_labels()[pid] + (", default" if pid == P.default_palette_id() else "")
        worst = min(min(cvd.worst_delta_e(P.categorical(pid, m))[0] for m in ("light", "dark")), 99)
        body.append(_text(16, y0 + 18, f"{label}  ({pid})", 13, weight=600))
        body.append(_text(16, y0 + 36, f"worst CVD pair dE {worst:.1f}", 11, "#868E96"))
        for c, mode in enumerate(("light", "dark")):
            x0 = 200 + c * 360
            ink = "#343A40" if mode == "light" else "#E9ECEF"
            body.append(_rect(x0, y0, 344, row_h - 12, BG[mode], 8, "#DEE2E6"))
            for i, colour in enumerate(P.categorical(pid, mode)):
                body.append(_rect(x0 + 12 + i * (SW + 6), y0 + 12, SW, SW, colour))
                body.append(
                    _text(
                        x0 + 12 + i * (SW + 6) + SW / 2, y0 + 60, str(i), 10, ink, anchor="middle"
                    )
                )
            body += _ramp(x0 + 12, y0 + 74, P.sequential(pid, mode), 314)
            body.append(_text(x0 + 12, y0 + 102, "sequential", 10, ink))
            body += _ramp(x0 + 12, y0 + 108, P.diverging(pid, mode), 314)
            body.append(_text(x0 + 12, y0 + 134, f"diverging ({mode})", 10, ink))
    return _svg(920, top + len(P.palette_ids()) * row_h, body)


def roles_sheet() -> str:
    """Colours that are not categorical slots: what each role draws, per mode."""
    body = [_text(16, 24, "Roles outside the categorical slots (default palette)", 14, weight=600)]
    rows: list[tuple[str, dict[str, str]]] = [
        ("Other (folded tail)", {m: P.semantic("other", m) for m in BG}),
        ("Unclassified / unknown", {m: P.semantic("unclassified", m) for m in BG}),
        ("NA / empty", {m: P.semantic("na", m) for m in BG}),
        ("Direction: up", {m: P.direction("up", m) for m in BG}),
        ("Direction: down", {m: P.direction("down", m) for m in BG}),
    ]
    impact = {m: P.ordinal_colors(["HIGH", "MODERATE", "LOW", "MODIFIER"], m) or {} for m in BG}
    for level in ("HIGH", "MODERATE", "LOW", "MODIFIER"):
        rows.append((f"snpEff impact: {level}", {m: impact[m][level] for m in BG}))
    rows.append(("Annotation ink (labels, notes)", {m: P.annotation_ink(m) for m in BG}))
    for key, name in (("text", "Chrome: text"), ("muted", "Chrome: muted / guide line")):
        rows.append((name, {m: P.chrome(m)[key] for m in BG}))
    y = 44
    for c, mode in enumerate(BG):
        body.append(_rect(250 + c * 230, y - 6, 214, len(rows) * 30 + 16, BG[mode], 8, "#DEE2E6"))
        body.append(_text(250 + c * 230 + 107, y - 12, mode, 11, "#868E96", anchor="middle"))
    for i, (name, by_mode) in enumerate(rows):
        yy = y + 6 + i * 30
        body.append(_text(16, yy + 16, name, 12))
        for c, mode in enumerate(BG):
            x = 262 + c * 230
            ink = "#343A40" if mode == "light" else "#E9ECEF"
            body.append(_rect(x, yy, 60, 22, by_mode[mode]))
            body.append(_text(x + 70, yy + 15, by_mode[mode], 11, ink))
    return _svg(720, y + len(rows) * 30 + 30, body)


def assignment_sheet() -> str:
    """Worked assignment examples: input values on the left, colours drawn on the right."""
    cases = [
        ("Case-insensitive order, whatever the data order", ["beta", "Alpha", "gamma"], {}, None),
        (
            "Reserved values take their grey, the rest the slots",
            ["Soil", "Other", "unclassified", "NA", "Sediment"],
            {},
            None,
        ),
        (
            "A pin wins; its colour leaves the pool",
            ["control", "treated", "recovery"],
            {"control": P.categorical()[4]},
            None,
        ),
        ("12 values, overflow: other (default)", [f"v{i:02d}" for i in range(12)], {}, "other"),
        ("12 values, overflow: shade", [f"v{i:02d}" for i in range(12)], {}, "shade"),
    ]
    body = [
        _text(16, 24, "Colour assignment, worked examples (default palette, light)", 14, weight=600)
    ]
    y = 48
    for title, values, pins, overflow in cases:
        out = P.assign_colors(values, pinned=pins, ranked=overflow is not None, overflow=overflow)
        body.append(_text(16, y + 4, title, 12, weight=600))
        if pins:
            body.append(
                _text(
                    16,
                    y + 20,
                    "pinned: " + ", ".join(f"{k} = {v}" for k, v in pins.items()),
                    11,
                    "#868E96",
                )
            )
        for i, v in enumerate(values):
            x = 16 + i * 66
            body.append(_rect(x, y + 28, 58, 26, out[v]))
            body.append(_text(x + 29, y + 68, v if v else "(empty)", 10, anchor="middle"))
        y += 96
    return _svg(16 + 12 * 66 + 10, y, body)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", type=Path, default=Path("docs/images/palettes"))
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for name, svg in (
        ("palettes", palettes_sheet()),
        ("roles", roles_sheet()),
        ("assignment", assignment_sheet()),
    ):
        (args.out_dir / f"{name}.svg").write_text(svg)
        print(args.out_dir / f"{name}.svg")


if __name__ == "__main__":
    main()
