"""The embed document declares the theme it was asked for, not the reader's.

The built bundle ships `<meta name="color-scheme" content="light dark">`, which
is correct for a page that follows the system setting. An embed is not that
page: the caller names a theme in the export URL. Until the app runs and
applies it, the browser paints the document's initial canvas from this meta, so
on a machine set to dark a light host page sees a black rectangle flash in
every framed component — four at once whenever a filter changes.
"""

from __future__ import annotations

from depictio.api.v1.services.export.embed import _declare_color_scheme

BUNDLE = '<html><head><meta name="color-scheme" content="light dark" /></head></html>'


def test_a_light_embed_says_light() -> None:
    assert '<meta name="color-scheme" content="light" />' in _declare_color_scheme(BUNDLE, "light")


def test_a_dark_embed_says_dark() -> None:
    assert '<meta name="color-scheme" content="dark" />' in _declare_color_scheme(BUNDLE, "dark")


def test_the_system_preference_is_never_left_in_place() -> None:
    assert "light dark" not in _declare_color_scheme(BUNDLE, "light")


def test_an_unknown_theme_falls_back_to_light() -> None:
    # `theme` reaches here as a string off the query; anything that is not the
    # one dark spelling has always meant the light rendering everywhere else.
    assert '<meta name="color-scheme" content="light" />' in _declare_color_scheme(BUNDLE, "")


def test_only_the_first_declaration_is_rewritten() -> None:
    # The rewrite must not touch a color-scheme the payload itself carries as
    # data further down the document.
    doubled = BUNDLE + '<meta name="color-scheme" content="light dark" />'
    assert _declare_color_scheme(doubled, "light").count("light dark") == 1


def test_a_bundle_without_the_meta_is_returned_unchanged(caplog) -> None:
    # A reshaped index template must not break the export; it should only warn.
    plain = "<html><head></head></html>"
    assert _declare_color_scheme(plain, "light") == plain
