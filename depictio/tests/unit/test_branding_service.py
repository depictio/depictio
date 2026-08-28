"""Instance brand theme service: env/DB merge, derivation, cache, upload rules."""

import json

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


@pytest.fixture()
def fake_assets(monkeypatch):
    fake = FakeCollection()
    monkeypatch.setattr(branding_svc, "branding_assets_collection", fake)
    return fake


class TestLogoAssetStore:
    """Uploaded logos live in MongoDB, so a rebuild cannot orphan the theme."""

    def test_round_trip_preserves_bytes_and_type(self, fake_assets):
        branding_svc.store_logo_asset("instance-light", PNG, "image/png")
        assert branding_svc.read_logo_asset("instance-light") == (PNG, "image/png")

    def test_missing_asset_reads_as_none(self, fake_assets):
        assert branding_svc.read_logo_asset("instance-dark") is None

    def test_replacing_keeps_one_document_per_key(self, fake_assets):
        branding_svc.store_logo_asset("instance-light", PNG, "image/png")
        branding_svc.store_logo_asset("instance-light", JPEG, "image/jpeg")
        assert branding_svc.read_logo_asset("instance-light") == (JPEG, "image/jpeg")
        assert len(fake_assets.docs) == 1

    def test_delete_removes_the_asset(self, fake_assets):
        branding_svc.store_logo_asset("dashboard-abc", PNG, "image/png")
        branding_svc.delete_logo_asset("dashboard-abc")
        assert branding_svc.read_logo_asset("dashboard-abc") is None

    def test_stored_document_is_json_serialisable(self, fake_assets):
        """The backup endpoint dumps with `json.dump(..., default=str)`, which
        turns raw bytes into an unrestorable repr. Base64 is what keeps a
        backed-up brand restorable."""
        branding_svc.store_logo_asset("instance-light", PNG, "image/png")
        doc = fake_assets.docs["instance-light"]
        assert isinstance(doc["data_b64"], str)
        assert json.loads(json.dumps(doc)) == doc

    def test_urls_point_at_the_serving_endpoints(self, fake_assets):
        instance_url = branding_svc.store_logo_asset("instance-dark", PNG, "image/png")
        dashboard_url = branding_svc.store_logo_asset("dashboard-42", PNG, "image/png")
        assert instance_url.startswith("/depictio/api/")
        assert "/utils/branding/logo/dark?v=" in instance_url
        assert "/dashboards/logo/42?v=" in dashboard_url

    def test_keys_are_scoped_by_owner(self):
        assert branding_svc.instance_logo_key("light") == "instance-light"
        assert branding_svc.dashboard_logo_key("abc123") == "dashboard-abc123"

    def test_content_type_lookup_is_the_inverse_of_validation(self):
        assert branding_svc.content_type_for_extension(".png") == "image/png"
        assert branding_svc.content_type_for_extension(".JPG") == "image/jpeg"
        assert branding_svc.content_type_for_extension(".svg") is None


class FakeDashboards:
    """Minimal `find` / `update_one` over a list, for the migration pass."""

    def __init__(self, docs):
        self.docs = docs

    def find(self, query, _projection=None):
        prefix = query["brand_theme.logo_url"]["$regex"].lstrip("^")
        return [
            d
            for d in self.docs
            if (d.get("brand_theme") or {}).get("logo_url", "").startswith(prefix)
        ]

    def update_one(self, query, update):
        for doc in self.docs:
            if doc["dashboard_id"] == query["dashboard_id"]:
                for key, value in update["$set"].items():
                    parent, _, child = key.partition(".")
                    doc.setdefault(parent, {})[child] = value


class TestLegacyLogoMigration:
    """Logos left on the container filesystem move into MongoDB on boot."""

    @pytest.fixture()
    def legacy_dir(self, tmp_path, monkeypatch):
        (tmp_path / "branding").mkdir()
        (tmp_path / "dashboard_logos").mkdir()
        monkeypatch.setattr(branding_svc, "_LEGACY_STATIC_DIR", tmp_path)
        return tmp_path

    @pytest.fixture()
    def fake_dashboards(self, monkeypatch):
        """Patched by default so no test reaches for a real Mongo connection."""
        fake = FakeDashboards([])
        monkeypatch.setattr("depictio.api.v1.db.dashboards_collection", fake)
        return fake

    def test_instance_logo_moves_and_url_is_rewritten(
        self, fake_store, fake_assets, fake_dashboards, legacy_dir
    ):
        (legacy_dir / "branding" / "logo_light.png").write_bytes(PNG)
        branding_svc.set_brand_theme_overrides(
            BrandTheme(logo_url="/static/branding/logo_light.png?v=1", logo_mode="custom")
        )

        assert branding_svc.migrate_legacy_logo_files() == 1

        overrides = branding_svc.get_brand_theme_overrides()
        assert "/utils/branding/logo/light" in overrides.logo_url
        # The rest of the brand is untouched by the rewrite.
        assert overrides.logo_mode == "custom"
        assert branding_svc.read_logo_asset("instance-light") == (PNG, "image/png")

    def test_already_migrated_instance_is_left_alone(
        self, fake_store, fake_assets, fake_dashboards, legacy_dir
    ):
        (legacy_dir / "branding" / "logo_light.png").write_bytes(PNG)
        branding_svc.set_brand_theme_overrides(
            BrandTheme(logo_url="/depictio/api/v1/utils/branding/logo/light?v=1")
        )
        assert branding_svc.migrate_legacy_logo_files() == 0
        assert fake_assets.docs == {}

    def test_missing_file_leaves_the_rest_of_the_brand_intact(
        self, fake_store, fake_assets, fake_dashboards, legacy_dir
    ):
        """The orphaned case: the URL survived, the file did not."""
        branding_svc.set_brand_theme_overrides(
            BrandTheme(logo_url="/static/branding/logo_light.png", app_name="Core Facility")
        )
        assert branding_svc.migrate_legacy_logo_files() == 0
        assert branding_svc.get_brand_theme_overrides().app_name == "Core Facility"

    def test_dashboard_logo_moves_and_url_is_rewritten(
        self, fake_store, fake_assets, fake_dashboards, legacy_dir
    ):
        (legacy_dir / "dashboard_logos" / "abc123.png").write_bytes(PNG)
        fake_dashboards.docs = [
            {
                "dashboard_id": "abc123",
                "brand_theme": {
                    "logo_url": "/static/dashboard_logos/abc123.png",
                    "logo_mode": "custom",
                },
            },
            {"dashboard_id": "untouched", "brand_theme": {"primary": "#123456"}},
        ]

        assert branding_svc.migrate_legacy_logo_files() == 1
        assert "/dashboards/logo/abc123" in fake_dashboards.docs[0]["brand_theme"]["logo_url"]
        assert fake_dashboards.docs[1]["brand_theme"] == {"primary": "#123456"}
        assert branding_svc.read_logo_asset("dashboard-abc123") == (PNG, "image/png")

    def test_one_half_failing_neither_raises_nor_stops_the_other(self, monkeypatch):
        """A deployment must still boot, and a dashboard tripping over
        something must not cost the instance its own logo."""

        def boom():
            raise RuntimeError("mongo down")

        monkeypatch.setattr(branding_svc, "_migrate_instance_logos", boom)
        monkeypatch.setattr(branding_svc, "_migrate_dashboard_logos", lambda: 1)
        assert branding_svc.migrate_legacy_logo_files() == 1
