"""Instance branding service: env/DB merge, cache invalidation, upload rules."""

import pytest

from depictio.api.v1.services import branding as branding_svc


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


class TestEffectiveBranding:
    def test_no_overrides_falls_back_to_env(self, fake_store):
        effective = branding_svc.get_effective_branding(use_cache=False)
        assert effective == branding_svc.env_branding_defaults()

    def test_override_wins_per_field(self, fake_store):
        branding_svc.set_branding_overrides({"app_name": "Core Facility"})
        effective = branding_svc.get_effective_branding(use_cache=False)
        assert effective["app_name"] == "Core Facility"
        # Untouched fields keep the env defaults.
        env = branding_svc.env_branding_defaults()
        assert effective["primary_color"] == env["primary_color"]
        assert effective["colorway"] == env["colorway"]

    def test_none_values_are_not_stored(self, fake_store):
        branding_svc.set_branding_overrides({"app_name": "X", "primary_color": None})
        assert branding_svc.get_branding_overrides() == {"app_name": "X"}

    def test_reset_clears_document(self, fake_store):
        branding_svc.set_branding_overrides({"app_name": "X"})
        branding_svc.set_branding_overrides({})
        assert branding_svc.get_branding_overrides() == {}
        assert fake_store.docs == {}

    def test_set_invalidates_cache(self, fake_store):
        # Prime the cache, then change the overrides: the cached value must
        # not survive the write.
        assert branding_svc.get_effective_branding()["app_name"] is None or True
        branding_svc.set_branding_overrides({"app_name": "Fresh"})
        assert branding_svc.get_effective_branding()["app_name"] == "Fresh"

    def test_update_single_field(self, fake_store):
        branding_svc.set_branding_overrides({"app_name": "X", "primary_color": "#0ca678"})
        branding_svc.update_branding_override("app_name", None)
        assert branding_svc.get_branding_overrides() == {"primary_color": "#0ca678"}
        with pytest.raises(ValueError):
            branding_svc.update_branding_override("nope", "x")


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
