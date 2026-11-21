"""depictio's plot palettes: colour-vision safety, contrast, assignment, TS freshness.

The parity cases in ``depictio/models/palettes/assign_cases.json`` are replayed by
``packages/depictio-react-core/src/palettes.test.ts``. After changing the assignment
rule or the palettes, regenerate them::

    uv run --extra dev python depictio/tests/unit/test_palettes.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from depictio.models import palettes
from depictio.models.palettes import cvd
from depictio.models.palettes.ui_hues import TEXT_CONTRAST

ROOT = Path(__file__).resolve().parents[3]
CASES = ROOT / "depictio" / "models" / "palettes" / "assign_cases.json"
DATA = palettes.load()
THRESHOLDS = DATA["thresholds"]
BACKGROUND = {"light": "#FFFFFF", "dark": "#1A1B1E"}


@pytest.mark.parametrize("palette_id", palettes.palette_ids())
@pytest.mark.parametrize("mode", ["light", "dark"])
def test_categorical_slots_stay_apart_under_every_vision(palette_id, mode):
    colours = palettes.categorical(palette_id, mode)
    assert len(colours) == DATA["slots"]
    worst, vision = cvd.worst_delta_e(colours)
    assert worst >= THRESHOLDS["min_cvd_delta_e"], (
        f"{palette_id}/{mode}: two slots are only ΔE2000 {worst:.1f} apart for {vision} vision"
    )


@pytest.mark.parametrize("palette_id", palettes.palette_ids())
@pytest.mark.parametrize("mode", ["light", "dark"])
def test_categorical_slots_read_on_their_background(palette_id, mode):
    floor = THRESHOLDS["min_contrast"][mode]
    for colour in palettes.categorical(palette_id, mode):
        ratio = cvd.contrast_ratio(colour, BACKGROUND[mode])
        assert ratio >= floor, f"{palette_id}/{mode} {colour}: contrast {ratio:.2f} < {floor}"


@pytest.mark.parametrize("palette_id", palettes.palette_ids())
@pytest.mark.parametrize("mode", ["light", "dark"])
def test_sequential_ramp_is_monotone_in_lightness(palette_id, mode):
    lightness = [
        cvd.lab(cvd.simulate(c, "normal"))[0] for c in palettes.sequential(palette_id, mode)
    ]
    steps = [b - a for a, b in zip(lightness, lightness[1:])]
    # light: background (light) end first, so lightness falls; dark: it rises
    assert all(s < 0 for s in steps) if mode == "light" else all(s > 0 for s in steps), lightness


@pytest.mark.parametrize("palette_id", palettes.palette_ids())
@pytest.mark.parametrize("mode", ["light", "dark"])
def test_diverging_ramp_has_a_neutral_middle(palette_id, mode):
    ramp = palettes.diverging(palette_id, mode)
    assert len(ramp) % 2 == 1
    _, a, b = cvd.lab(cvd.simulate(ramp[len(ramp) // 2], "normal"))
    assert (a * a + b * b) ** 0.5 < 3, "the middle stop must be a neutral grey"


def test_annotation_ink_stands_apart_from_every_data_colour():
    for mode in ("light", "dark"):
        ink = palettes.annotation_ink(mode)
        for palette_id in palettes.palette_ids():
            for colour in palettes.categorical(palette_id, mode):
                for vision in cvd.VISIONS:
                    d = cvd.delta_e(
                        cvd.lab(cvd.simulate(ink, vision)), cvd.lab(cvd.simulate(colour, vision))
                    )
                    assert d >= THRESHOLDS["min_cvd_delta_e"], (palette_id, mode, colour, vision, d)


def test_default_palette_is_listed_first():
    assert palettes.palette_ids()[0] == palettes.default_palette_id() == "marque"


def test_unknown_palette_falls_back_to_default():
    assert palettes.categorical("no-such-palette") == palettes.categorical(None)


@pytest.mark.parametrize(
    "value, kind",
    [
        ("Other", "other"),
        (" others ", "other"),
        ("Unclassified", "unclassified"),
        ("unknown", "unclassified"),
        ("NA", "na"),
        ("", "na"),
        (None, "na"),
        ("Soil", None),
    ],
)
def test_reserved_kind(value, kind):
    assert palettes.reserved_kind(value) == kind


def test_assignment_ignores_filtering():
    universe = ["control", "treated", "recovery"]
    # input order never matters: the map depends on the set of values only
    assert palettes.assign_colors(universe) == palettes.assign_colors(list(reversed(universe)))


def test_remainder_moves_last_in_order():
    assert palettes.order_with_remainder_last(["NA", "b", "Other", "a", "Unclassified"]) == [
        "b",
        "a",
        "Other",
        "Unclassified",
        "NA",
    ]


def test_style_block_constants():
    style = palettes.style()
    assert style["bar_corner_radius"] == 4
    assert style["top_n"] == 8


def test_scatter_buckets_get_smaller_and_fainter_and_the_last_is_open():
    buckets = palettes.style()["scatter_markers"]
    ceilings = [b["max_n"] for b in buckets[:-1]]
    assert ceilings == sorted(ceilings) and None not in ceilings
    assert buckets[-1]["max_n"] is None
    sizes = [b["size"] for b in buckets]
    opacities = [b["opacity"] for b in buckets]
    assert sizes == sorted(sizes, reverse=True) and len(set(sizes)) == len(sizes)
    assert opacities == sorted(opacities, reverse=True) and len(set(opacities)) == len(opacities)


@pytest.mark.parametrize(
    ("n", "size"),
    [(0, 9), (50, 9), (51, 7), (500, 7), (501, 5), (5000, 5), (5001, 3.5), (10_000_000, 3.5)],
)
def test_scatter_marker_picks_the_first_bucket_that_fits(n, size):
    assert palettes.scatter_marker(n)["size"] == size


def test_only_dense_scatters_lose_their_outline():
    assert palettes.scatter_marker(10)["outline"] is True
    assert palettes.scatter_marker(100_000)["outline"] is False


def test_overflow_argument_overrides_the_default():
    values = [f"v{i}" for i in range(10)]
    grey = palettes.semantic("other", "light")
    other = palettes.assign_colors(values, ranked=True, overflow="other")
    shade = palettes.assign_colors(values, ranked=True, overflow="shade")
    assert other["v8"] == other["v9"] == grey
    assert grey not in (shade["v8"], shade["v9"])
    assert len(set(shade.values())) == 10


def test_named_palette_of_recognises_a_palette_list_only():
    pid = palettes.default_palette_id()
    assert palettes.named_palette_of(None) == pid
    assert palettes.named_palette_of(palettes.categorical(pid, "dark"), "dark") == pid
    assert palettes.named_palette_of(["#111111", "#222222"]) is None


def test_brand_plots_accepts_overflow():
    from depictio.models.models.branding import BrandPlots

    assert BrandPlots(overflow="shade").overflow == "shade"
    assert not BrandPlots(overflow="other").is_empty
    with pytest.raises(ValueError):
        BrandPlots(overflow="rainbow")


def _compute_cases() -> list[dict]:
    cases = json.loads(CASES.read_text())["cases"]
    for case in cases:
        case["expected"] = palettes.assign_colors(
            case["values"],
            pinned=case["pinned"],
            palette=case["palette"],
            mode=case["mode"],
            ranked=case.get("ranked", False),
            overflow=case.get("overflow"),
        )
    return cases


def test_parity_cases_are_current():
    stored = json.loads(CASES.read_text())["cases"]
    assert stored == _compute_cases(), "assign_cases.json is stale: run this file as a script"


def test_generated_typescript_is_fresh():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gen_palette_ts.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


if __name__ == "__main__":
    payload = json.loads(CASES.read_text())
    payload["cases"] = _compute_cases()
    CASES.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"rewrote {CASES.relative_to(ROOT)}")


# ── UI hues: Mantine names re-drawn in the palette inside a dashboard ───────────

_UI_PAIRS = [("violet", "grape"), ("teal", "cyan"), ("blue", "indigo"), ("green", "lime")]
_ANCHOR = {"light": 6, "dark": 4}


def _lightness(hex_color: str) -> float:
    return cvd.lab(cvd.simulate(hex_color, "normal"))[0]


@pytest.mark.parametrize("palette_id", palettes.palette_ids())
@pytest.mark.parametrize("mode", ["light", "dark"])
def test_ui_hue_tuples_are_monotone_and_anchored(palette_id, mode):
    assert palettes.ui_hue_names() == list(DATA["ui_hues"]["default"])
    for name in palettes.ui_hue_names():
        tup = palettes.ui_hue_tuple(name, palette_id, mode)
        assert len(tup) == 10
        # one lightness per shade, light to dark (a hair of slack for 8-bit rounding)
        lightness = [_lightness(c) for c in tup]
        assert all(a > b - 0.3 for a, b in zip(lightness, lightness[1:])), (name, lightness)
        assert lightness[0] > lightness[-1] + 30
        assert tup[_ANCHOR[mode]] == palettes.ui_hue_anchor(name, palette_id, mode).upper()


@pytest.mark.parametrize("palette_id", palettes.palette_ids())
def test_unadjusted_ui_hues_are_the_slot_colour_made_readable(palette_id):
    specs = {**DATA["ui_hues"]["default"], **DATA["ui_hues"]["per_palette"].get(palette_id, {})}
    for mode in ("light", "dark"):
        slots = palettes.categorical(palette_id, mode)
        for name, spec in specs.items():
            slot = slots[spec["slot"]].upper()
            if {"dL", "dC", "dh"} & spec.keys():
                continue
            anchor = palettes.ui_hue_anchor(name, palette_id, mode)
            # The slot colour itself, unless it had to be deepened to read as text;
            # then the same hue, as close to it as the contrast floor allows.
            if cvd.contrast_ratio(slot, BACKGROUND[mode]) >= TEXT_CONTRAST:
                assert anchor == slot
            else:
                assert cvd.contrast_ratio(anchor, BACKGROUND[mode]) < TEXT_CONTRAST + 0.3


@pytest.mark.parametrize("palette_id", palettes.palette_ids())
@pytest.mark.parametrize("mode", ["light", "dark"])
def test_ui_hue_pairs_stay_visibly_apart(palette_id, mode):
    shade = _ANCHOR[mode]
    for a, b in _UI_PAIRS:
        ca = palettes.ui_hue_tuple(a, palette_id, mode)[shade]
        cb = palettes.ui_hue_tuple(b, palette_id, mode)[shade]
        d = cvd.delta_e(cvd.lab(cvd.simulate(ca, "normal")), cvd.lab(cvd.simulate(cb, "normal")))
        assert d >= 5, f"{palette_id}/{mode} {a} vs {b}: ΔE2000 {d:.1f}"


@pytest.mark.parametrize("palette_id", palettes.palette_ids())
@pytest.mark.parametrize("mode", ["light", "dark"])
def test_ui_hues_read_on_their_background(palette_id, mode):
    # The chrome writes text in these hues (findings numbers, tab links), so the
    # anchor shade meets WCAG AA for normal text, above the data slots' own floors.
    floor = TEXT_CONTRAST
    for name in palettes.ui_hue_names():
        colour = palettes.ui_hue_tuple(name, palette_id, mode)[_ANCHOR[mode]]
        ratio = cvd.contrast_ratio(colour, BACKGROUND[mode])
        assert ratio >= floor, (
            f"{palette_id}/{mode} {name} {colour}: contrast {ratio:.2f} < {floor}"
        )


def test_ui_hues_never_remap_neutrals_or_the_brand():
    names = set(palettes.ui_hue_names())
    assert not names & {"gray", "dark", "black", "white", "brandPrimary"}


def test_unknown_palette_ui_hue_falls_back_to_default():
    assert palettes.ui_hue_tuple("teal", "nope") == palettes.ui_hue_tuple("teal", None)
