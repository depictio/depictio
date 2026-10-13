"""Brand palette derivation: determinism, separation, and the merge fold.

The derived figure colors are computed once server-side and shipped to the SPA
precisely so the two can't drift, which makes these the contract tests for that
promise: same input, same output, and output good enough to plot with.
"""

import re

import pytest

from depictio.models.models.branding import (
    BRAND_PRESETS,
    PALETTE_LENGTH,
    BrandPlots,
    BrandSurfaces,
    BrandTheme,
    derive_colorway,
    derive_palette,
    derive_sequential,
    merge_brand_themes,
    preset_theme,
    relative_luminance,
    resolve_brand_theme,
    shift_lightness,
)

TREC = ["#00a550", "#1a4f8f", "#f5a11b"]
HEX = re.compile(r"^#[0-9a-f]{6}$")


class TestColorway:
    def test_is_deterministic(self):
        assert derive_colorway(TREC) == derive_colorway(TREC)

    def test_opens_on_the_brand_hues_in_order(self):
        assert derive_colorway(TREC)[:3] == TREC

    def test_has_no_duplicates(self):
        assert len(set(derive_colorway(TREC))) == len(derive_colorway(TREC))

    def test_adjacent_entries_differ_in_hue(self):
        """Neighbouring series are what a reader compares first."""
        colors = derive_colorway(TREC)
        for a, b in zip(colors, colors[1:]):
            assert a != b

    def test_single_hue_still_spreads(self):
        colors = derive_colorway(["#1c7ed6"])
        assert colors[0] == "#1c7ed6"
        assert len(set(colors)) == len(colors)

    def test_ignores_palette_names_and_empties(self):
        # A Mantine palette name is legal on the model but has no hex to
        # rotate, so derivation skips it rather than guessing.
        assert derive_colorway(["teal"]) == []
        assert derive_colorway([]) == []

    def test_dark_seed_never_collapses_to_black(self):
        for color in derive_colorway(["#0b1b2b", "#00514b"]):
            assert relative_luminance(color) > 0.004

    def test_length_is_respected(self):
        assert len(derive_colorway(TREC, length=5)) == 5
        assert len(derive_colorway(TREC, length=12)) == 12


class TestSequential:
    def test_is_deterministic(self):
        assert derive_sequential("#00a550") == derive_sequential("#00a550")

    def test_runs_light_to_dark(self):
        stops = derive_sequential("#00a550")
        luminance = [relative_luminance(c) for c in stops]
        assert luminance == sorted(luminance, reverse=True)

    def test_needs_a_hex_seed(self):
        assert derive_sequential("teal") == []
        assert derive_sequential("") == []


class TestShiftLightness:
    def test_reflects_instead_of_clipping(self):
        """An already-dark color darkened again gets lighter, not black."""
        assert relative_luminance(shift_lightness("#00514b", -0.3)) > relative_luminance("#00514b")

    def test_lightening_relaxes_saturation(self):
        # Straight HLS lightening at full saturation yields neon (#00f778).
        assert shift_lightness("#00a550", 0.18) != "#00f778"


class TestResolve:
    def test_fills_derived_values_and_defaults(self):
        resolved = resolve_brand_theme(BrandTheme(primary="#00a550"))
        assert resolved.tint_mode == "accent"
        assert resolved.logo_mode == "inherit"
        assert resolved.plots is not None
        assert resolved.plots.colorway[0] == "#00a550"

    def test_is_idempotent(self):
        once = resolve_brand_theme(BrandTheme(primary="#00a550"))
        assert resolve_brand_theme(once) == once

    def test_does_not_mutate_its_input(self):
        theme = BrandTheme(primary="#00a550")
        resolve_brand_theme(theme)
        assert theme.plots is None
        assert theme.tint_mode is None

    def test_a_logo_url_alone_implies_custom_mode(self):
        assert resolve_brand_theme(BrandTheme(logo_url="/x.png")).logo_mode == "custom"

    def test_an_explicit_none_mode_is_kept(self):
        theme = BrandTheme(logo_mode="none", logo_url="/x.png")
        assert resolve_brand_theme(theme).logo_mode == "none"

    def test_empty_theme_derives_nothing(self):
        assert resolve_brand_theme(BrandTheme()).plots is None


class TestMerge:
    def test_later_layers_win_per_field(self):
        merged = merge_brand_themes(
            BrandTheme(primary="#111111", secondary="#222222"),
            BrandTheme(primary="#333333"),
        )
        assert merged.primary == "#333333"
        assert merged.secondary == "#222222"

    def test_none_layers_are_skipped(self):
        assert merge_brand_themes(None, BrandTheme(primary="#111111"), None).primary == "#111111"

    def test_nested_surfaces_merge(self):
        merged = merge_brand_themes(
            BrandTheme(surfaces_light=BrandSurfaces(nav_bg="#eeeeee")),
            BrandTheme(surfaces_light=BrandSurfaces(app_bg="#ffffff")),
        )
        assert merged.surfaces_light is not None
        assert merged.surfaces_light.nav_bg == "#eeeeee"
        assert merged.surfaces_light.app_bg == "#ffffff"

    def test_nested_plots_merge(self):
        merged = merge_brand_themes(
            BrandTheme(plots=BrandPlots(template="seaborn")),
            BrandTheme(plots=BrandPlots(colorway=["#111111"])),
        )
        assert merged.plots is not None
        assert merged.plots.template == "seaborn"
        assert merged.plots.colorway == ["#111111"]

    def test_merging_nothing_is_empty(self):
        assert merge_brand_themes().is_empty


class TestPresets:
    @pytest.mark.parametrize("preset_id", sorted(BRAND_PRESETS))
    def test_every_preset_is_a_valid_theme(self, preset_id):
        theme = preset_theme(preset_id)
        assert theme is not None
        resolved = resolve_brand_theme(theme)
        # The default preset is deliberately empty (stock Mantine).
        if theme.is_empty:
            assert resolved.plots is None
        else:
            assert resolved.plots is not None
            assert len(resolved.plots.colorway) == 8

    def test_unknown_preset_is_none(self):
        assert preset_theme("nope") is None
        assert preset_theme("") is None

    def test_lookup_is_case_insensitive(self):
        assert preset_theme("TREC") == preset_theme("trec")


#: Seeds at both ends of the lightness range. The near-black and near-white
#: entries are the ones that caught an inverted ramp: each bound used to be a
#: fixed clamp, so a seed past it landed on the wrong side of its own anchor
#: and shades 7-9 (hover, pressed) came out lighter than the button.
EXTREMES = [
    "#00514b",
    "#ff0000",
    "#f0f0f0",
    "#101820",
    "#1a0000",
    "#001100",
    "#000000",
    "#ffffff",
]


class TestDerivePalette:
    """The Mantine tuple built for a brand role.

    Mantine paints a filled control with shade 6 (light) / shade 8 (dark), so
    where the brand color lands in the tuple decides whether a button is the
    brand or merely near it.
    """

    @pytest.mark.parametrize("base", TREC + EXTREMES)
    def test_brand_color_is_the_filled_shade(self, base):
        assert derive_palette(base)[6] == base.lower()

    @pytest.mark.parametrize("base", TREC + EXTREMES)
    def test_tuple_is_ten_shades_of_hex(self, base):
        shades = derive_palette(base)
        assert len(shades) == PALETTE_LENGTH
        assert all(HEX.fullmatch(shade) for shade in shades)

    @pytest.mark.parametrize("base", TREC + EXTREMES)
    def test_shades_darken_monotonically(self, base):
        """A ramp that doubles back reads as a mistake in every hover state."""
        lums = [relative_luminance(shade) for shade in derive_palette(base)]
        assert all(a >= b - 1e-9 for a, b in zip(lums, lums[1:]))

    def test_dark_seed_keeps_its_shades_distinct(self):
        """`#00514b` is dark enough that a naive ramp collapses 7-9 into black."""
        shades = derive_palette("#00514b")
        assert len(set(shades)) == PALETTE_LENGTH

    @pytest.mark.parametrize("base", ["#1a0000", "#001100", "#0a0a0a"])
    def test_near_black_seed_still_darkens_below_the_anchor(self, base):
        """The floor must sit under the seed, not over it.

        A brand darker than a fixed floor used to ramp *upwards* from shade 6,
        so `#1a0000` bottomed out at `#290000` and every pressed state painted
        lighter than the button it belonged to.
        """
        shades = derive_palette(base)
        anchor = relative_luminance(shades[6])
        assert all(relative_luminance(shade) <= anchor + 1e-9 for shade in shades[7:])

    @pytest.mark.parametrize("base", ["#ffffff", "#fefefe", "#f8f9fa"])
    def test_near_white_seed_still_lightens_above_the_anchor(self, base):
        """The same trap mirrored: the tint ceiling must sit over the seed."""
        shades = derive_palette(base)
        anchor = relative_luminance(shades[6])
        assert all(relative_luminance(shade) >= anchor - 1e-9 for shade in shades[:6])

    def test_is_deterministic(self):
        assert derive_palette("#00a550") == derive_palette("#00a550")

    def test_rejects_non_hex(self):
        assert derive_palette("blue") == []
        assert derive_palette("") == []


class TestResolvedPalettes:
    def test_hex_roles_get_a_tuple(self):
        resolved = resolve_brand_theme(preset_theme("trec"))
        assert set(resolved.palettes) == {"primary", "secondary", "tertiary"}
        assert resolved.palettes["primary"][6] == "#00a550"

    def test_palette_names_are_left_to_mantine(self):
        """A role named `grape` already has a tuple client-side."""
        resolved = resolve_brand_theme(BrandTheme(primary="grape", secondary="#1a4f8f"))
        assert set(resolved.palettes) == {"secondary"}

    def test_unbranded_theme_derives_nothing(self):
        assert resolve_brand_theme(BrandTheme()).palettes is None

    def test_derived_tuples_do_not_make_a_theme_non_empty(self):
        """Otherwise every untouched dashboard would export a brand block."""
        assert BrandTheme(palettes={"primary": derive_palette("#00a550")}).is_empty

    def test_rejects_a_tuple_of_the_wrong_length(self):
        with pytest.raises(ValueError):
            BrandTheme(palettes={"primary": ["#00a550"]})
