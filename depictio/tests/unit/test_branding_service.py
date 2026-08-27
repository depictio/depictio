"""Instance brand theme service: env/DB merge, derivation, cache, upload rules."""

import pytest

from depictio.api.v1.services import branding as branding_svc
from depictio.models.models.branding import BrandPlots, BrandTheme, merge_brand_themes


class FakeCollection:
    """Just enough of a pymongo collection for the singleton-document flows."""

    def __init__(self):
        self.docs: dict[str, dict] = {}

    def find_one(self, query):
        return self.docs.get(query["_id"])

    def replace_one(self, query, doc, upsert=False):
        self.docs[query["_id"]] = {"_id": query["_id"], **doc}

    def delete_one(self, query):
        self.docs.pop(query["_id"], None)

    def update_one(self, query, update, upsert=False):
        doc = self.docs.get(query["_id"])
        if doc is None:
            if not upsert and "$set" in update:
                return
            doc = {"_id": query["_id"]}
            self.docs[query["_id"]] = doc
        for key, value in update.get("$set", {}).items():
            doc[key] = value
        for key in update.get("$unset", {}):
            doc.pop(key, None)


@pytest.fixture()
def fake_store(monkeypatch):
    fake = FakeCollection()
    monkeypatch.setattr(branding_svc, "instance_settings_collection", fake)
    branding_svc.invalidate_branding_cache()
    yield fake
    branding_svc.invalidate_branding_cache()


class TestEffectiveBrandTheme:
    def test_no_overrides_falls_back_to_env(self, fake_store):
        assert branding_svc.get_effective_brand_theme(use_cache=False) == (
            branding_svc.env_brand_theme()
        )

    def test_override_wins_per_field(self, fake_store):
        branding_svc.set_brand_theme_overrides(BrandTheme(app_name="Core Facility"))
        effective = branding_svc.get_effective_brand_theme(use_cache=False)
        assert effective.app_name == "Core Facility"
        # Untouched fields keep the env defaults.
        env = branding_svc.env_brand_theme()
        assert effective.primary == env.primary
        assert effective.plots == env.plots

    def test_nested_blocks_merge_field_wise(self, fake_store):
        """A dashboard/admin layer that sets one plot key keeps the others."""
        branding_svc.set_brand_theme_overrides(
            BrandTheme(plots=BrandPlots(template="seaborn", colorway=["#111111"]))
        )
        merged = merge_brand_themes(
            branding_svc.get_effective_brand_theme(use_cache=False),
            BrandTheme(plots=BrandPlots(colorway=["#222222"])),
        )
        assert merged.plots is not None
        assert merged.plots.template == "seaborn"
        assert merged.plots.colorway == ["#222222"]

    def test_none_values_are_not_stored(self, fake_store):
        branding_svc.set_brand_theme_overrides(BrandTheme(app_name="X", primary=None))
        assert branding_svc.get_brand_theme_overrides().model_dump(exclude_none=True) == {
            "app_name": "X"
        }

    def test_reset_clears_document(self, fake_store):
        branding_svc.set_brand_theme_overrides(BrandTheme(app_name="X"))
        branding_svc.set_brand_theme_overrides(None)
        assert branding_svc.get_brand_theme_overrides().is_empty
        assert fake_store.docs == {}

    def test_set_invalidates_cache(self, fake_store):
        # Prime the cache, then change the overrides: the cached value must
        # not survive the write.
        branding_svc.get_effective_brand_theme()
        branding_svc.set_brand_theme_overrides(BrandTheme(app_name="Fresh"))
        assert branding_svc.get_effective_brand_theme().app_name == "Fresh"

    def test_patch_touches_only_the_named_fields(self, fake_store):
        branding_svc.set_brand_theme_overrides(BrandTheme(app_name="X", primary="#0ca678"))
        branding_svc.patch_brand_theme_overrides({"app_name": None})
        assert branding_svc.get_brand_theme_overrides().model_dump(exclude_none=True) == {
            "primary": "#0ca678"
        }
        with pytest.raises(ValueError):
            branding_svc.patch_brand_theme_overrides({"nope": "x"})

    def test_legacy_flat_document_is_still_readable(self, fake_store):
        """A dev instance branded before the BrandTheme rework keeps its logo."""
        fake_store.docs["branding"] = {
            "_id": "branding",
            "app_name": "Old",
            "primary_color": "#0ca678",
            "logo_url": "/static/branding/logo_light.png",
            "colorway": ["#111111", "#222222"],
        }
        overrides = branding_svc.get_brand_theme_overrides()
        assert overrides.app_name == "Old"
        assert overrides.primary == "#0ca678"
        assert overrides.logo_url == "/static/branding/logo_light.png"
        assert overrides.plots is not None
        assert overrides.plots.colorway == ["#111111", "#222222"]


class TestResolvedBrandTheme:
    """The wire format: derived values materialised once, server-side."""

    def test_palette_derives_figure_colors(self, fake_store):
        branding_svc.set_brand_theme_overrides(
            BrandTheme(primary="#00a550", secondary="#1a4f8f", tertiary="#f5a11b")
        )
        resolved = branding_svc.resolve_effective_brand_theme(use_cache=False)
        assert resolved.plots is not None
        assert resolved.plots.colorway[:3] == ["#00a550", "#1a4f8f", "#f5a11b"]
        assert len(resolved.plots.sequential) > 1

    def test_explicit_colorway_is_not_overwritten(self, fake_store):
        branding_svc.set_brand_theme_overrides(
            BrandTheme(primary="#00a550", plots=BrandPlots(colorway=["#123456"]))
        )
        resolved = branding_svc.resolve_effective_brand_theme(use_cache=False)
        assert resolved.plots.colorway == ["#123456"]

    def test_defaults_are_explicit(self, fake_store):
        resolved = branding_svc.resolve_effective_brand_theme(use_cache=False)
        assert resolved.tint_mode == "accent"
        assert resolved.logo_mode == "inherit"


PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 16
JPEG = b"\xff\xd8\xff" + b"0" * 16
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"0" * 8


class TestLogoUploadValidation:
    def test_accepts_matching_content(self):
        assert branding_svc.validate_logo_upload("image/png", PNG) == ".png"
        assert branding_svc.validate_logo_upload("image/jpeg", JPEG) == ".jpg"
        assert branding_svc.validate_logo_upload("image/webp", WEBP) == ".webp"

    def test_rejects_svg(self):
        with pytest.raises(ValueError, match="Unsupported"):
            branding_svc.validate_logo_upload("image/svg+xml", b"<svg/>")

    def test_rejects_mismatched_magic(self):
        with pytest.raises(ValueError, match="does not match"):
            branding_svc.validate_logo_upload("image/png", JPEG)
        # RIFF container that is not WEBP (e.g. a WAV) is refused too.
        with pytest.raises(ValueError, match="does not match"):
            branding_svc.validate_logo_upload("image/webp", b"RIFF\x00\x00\x00\x00WAVE")

    def test_rejects_oversize(self):
        big = PNG + b"0" * branding_svc.LOGO_MAX_BYTES
        with pytest.raises(ValueError, match="too large"):
            branding_svc.validate_logo_upload("image/png", big)
