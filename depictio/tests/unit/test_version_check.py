"""Release check: version ordering, enable matrix, claim, fetch and views."""

import asyncio
from datetime import timedelta

import httpx
import mongomock
import pytest

from depictio.api.v1.configs.config import settings
from depictio.api.v1.services import branding as branding_svc
from depictio.api.v1.services import version_check as vc
from depictio.models.timestamps import utc_now_naive

CURRENT_STABLE = "1.15.1"
CURRENT_BETA = "1.15.1-b3"


@pytest.fixture()
def store(monkeypatch):
    """The `instance_settings` collection, on mongomock, with a clean cache."""
    collection = mongomock.MongoClient()["depictio_test"]["instance_settings"]
    monkeypatch.setattr(branding_svc, "instance_settings_collection", collection)
    monkeypatch.setattr(settings.version_check, "enabled", None)
    monkeypatch.setattr(settings.version_check, "interval_hours", 6)
    vc.invalidate_version_check_cache()
    yield collection
    vc.invalidate_version_check_cache()


def _release(tag, *, draft=False, prerelease=False, published="2026-03-04T05:06:07Z"):
    return {
        "tag_name": tag,
        "name": f"Release {tag}",
        "draft": draft,
        "prerelease": prerelease,
        "html_url": f"https://github.com/depictio/depictio/releases/tag/{tag}",
        "published_at": published,
    }


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://api.github.com/x")
            raise httpx.HTTPStatusError(
                "bad", request=request, response=httpx.Response(self.status_code, request=request)
            )

    def json(self):
        return self._payload


@pytest.fixture()
def github(monkeypatch):
    """Replace `httpx.AsyncClient` with a recorder returning `github.responses[url_suffix]`."""

    class Recorder:
        calls: list[dict] = []
        responses: dict[str, object] = {}
        error: Exception | None = None

    recorder = Recorder()
    recorder.calls = []
    recorder.responses = {}

    class FakeClient:
        def __init__(self, *, timeout=None, **_):
            recorder.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None, headers=None):
            recorder.calls.append({"url": url, "params": params, "headers": headers})
            if recorder.error is not None:
                raise recorder.error
            key = "list" if url.endswith("/releases") else "latest"
            return recorder.responses[key]

    monkeypatch.setattr(vc.httpx, "AsyncClient", FakeClient)
    return recorder


@pytest.fixture()
def current(monkeypatch):
    def _set(version):
        monkeypatch.setattr(vc, "get_version", lambda: version)

    return _set


class TestVersionOrdering:
    def test_beta_precedes_its_release_and_order_is_total(self):
        ordered = ["1.15.1-b3", "1.15.1", "1.15.2-b1", "1.16.0"]
        keys = [vc.parse_version(v) for v in ordered]
        assert all(k is not None for k in keys)
        assert keys == sorted(keys)
        assert len(set(keys)) == len(keys)

    def test_beta_numbers_compare_numerically(self):
        assert vc.is_newer("1.0.0-b10", "1.0.0-b9")

    def test_v_prefix_is_accepted(self):
        assert vc.parse_version("v1.2.3") == vc.parse_version("1.2.3")
        assert vc.parse_version("v1.2.3-b4") == vc.parse_version("1.2.3-b4")

    @pytest.mark.parametrize("garbage", [None, "", "latest", "1.2", "1.2.3.4", "1.2.3-rc1", "v"])
    def test_garbage_is_unparsable(self, garbage):
        assert vc.parse_version(garbage) is None

    def test_is_newer(self):
        assert vc.is_newer("1.15.1", "1.15.1-b3")
        assert vc.is_newer("v1.16.0", "1.15.1")
        assert not vc.is_newer("1.15.1", "1.15.1")
        assert not vc.is_newer("1.15.1-b3", "1.15.1")
        assert not vc.is_newer("garbage", "1.15.1")
        assert not vc.is_newer("1.15.1", "garbage")


class TestEffectiveEnabled:
    @pytest.mark.parametrize("override", [None, True, False])
    @pytest.mark.parametrize("env", [None, True, False])
    def test_matrix(self, store, monkeypatch, env, override):
        monkeypatch.setattr(settings.version_check, "enabled", env)
        if override is not None:
            vc.set_override(override)
        if env is not None:
            expected = env
        elif override is not None:
            expected = override
        else:
            expected = True
        assert vc.is_enabled() is expected
        assert vc.locked_by_env() is (env is not None)

    def test_clearing_the_override_restores_the_default(self, store):
        vc.set_override(False)
        assert vc.is_enabled() is False
        vc.set_override(None)
        assert vc.is_enabled() is True
        assert "enabled_override" not in store.find_one({"_id": "version_check"})

    def test_mongo_down_defaults_to_on(self, monkeypatch):
        class Down:
            def find_one(self, *_):
                raise RuntimeError("no mongo")

        monkeypatch.setattr(branding_svc, "instance_settings_collection", Down())
        monkeypatch.setattr(settings.version_check, "enabled", None)
        vc.invalidate_version_check_cache()
        assert vc.is_enabled() is True
        vc.invalidate_version_check_cache()


class TestStateCache:
    def test_admin_view_reads_past_a_stale_cache(self, store):
        assert vc.is_enabled() is True  # primes the cache
        # Another worker's PUT: this process' cache knows nothing about it.
        store.update_one(
            {"_id": "version_check"}, {"$set": {"enabled_override": False}}, upsert=True
        )
        assert vc.is_enabled() is True
        assert vc.admin_view()["enabled"] is False
        assert vc.admin_view()["override"] is False

    def test_failed_read_is_not_cached(self, monkeypatch, store):
        vc.set_override(False)
        vc.invalidate_version_check_cache()
        real = vc.get_instance_settings_collection

        class Down:
            def find_one(self, *_):
                raise RuntimeError("no mongo")

        monkeypatch.setattr(vc, "get_instance_settings_collection", lambda: Down())
        assert vc.is_enabled() is True  # unreachable: falls back to on
        monkeypatch.setattr(vc, "get_instance_settings_collection", real)
        # The outage left nothing behind: the admin's "off" is seen again at once.
        assert vc.is_enabled() is False


class TestSettingsEnv:
    def test_empty_strings_read_as_unset(self, monkeypatch):
        from depictio.api.v1.configs.settings_models import VersionCheckConfig

        monkeypatch.setenv("DEPICTIO_VERSION_CHECK_ENABLED", "")
        monkeypatch.setenv("DEPICTIO_VERSION_CHECK_INTERVAL_HOURS", "")
        cfg = VersionCheckConfig()
        assert cfg.enabled is None
        assert cfg.interval_hours == 6

    @pytest.mark.parametrize("raw,expected", [("false", False), ("true", True)])
    def test_explicit_values_are_forced(self, monkeypatch, raw, expected):
        from depictio.api.v1.configs.settings_models import VersionCheckConfig

        monkeypatch.setenv("DEPICTIO_VERSION_CHECK_ENABLED", raw)
        assert VersionCheckConfig().enabled is expected


class TestClaim:
    def test_first_wins_second_loses_until_due(self, store):
        now = utc_now_naive()
        assert vc._claim(now) is True
        assert vc._claim(now + timedelta(minutes=1)) is False
        assert vc._claim(now + timedelta(hours=5, minutes=59)) is False
        assert vc._claim(now + timedelta(hours=6, seconds=1)) is True

    def test_claim_works_on_a_document_that_only_holds_an_override(self, store):
        vc.set_override(False)
        assert vc._claim(utc_now_naive()) is True
        assert vc._claim(utc_now_naive()) is False

    @pytest.mark.parametrize("restored", ["2026-01-01T00:00:00", "", None, 0])
    def test_claim_works_on_a_restored_non_date_next_check_at(self, store, restored):
        # A backup restore writes the datetimes back as strings; neither `$lte` nor
        # `$exists: False` matches those, which used to fail every claim for good.
        store.insert_one({"_id": "version_check", "next_check_at": restored})
        now = utc_now_naive()
        assert vc._claim(now) is True
        # Compared to the second: the store keeps milliseconds.
        stored = store.find_one({"_id": "version_check"})["next_check_at"]
        assert abs(stored - (now + timedelta(hours=6))) < timedelta(seconds=1)
        assert vc._claim(now) is False

    def test_string_timestamps_do_not_break_the_views(self, store, current):
        current(CURRENT_STABLE)
        store.insert_one(
            {
                "_id": "version_check",
                "checked_at": "2026-01-01T00:00:00",
                "latest": {"version": "1.16.0", "published_at": "2026-01-01T00:00:00"},
            }
        )
        view = vc.admin_view()
        assert view["checked_at"] is None
        assert view["published_at"] is None
        assert view["latest_version"] == "1.16.0"

    def test_mongo_unreachable_means_no_check(self, monkeypatch):
        class Down:
            def find_one_and_update(self, *_, **__):
                raise RuntimeError("no mongo")

        monkeypatch.setattr(branding_svc, "instance_settings_collection", Down())
        assert vc._claim(utc_now_naive()) is False


class TestFetch:
    def test_stable_asks_releases_latest(self, store, github, current):
        current(CURRENT_STABLE)
        github.responses["latest"] = FakeResponse(_release("v1.16.0"))
        view = asyncio.run(vc.run_version_check(force=True))

        (call,) = github.calls
        assert call["url"].endswith("/repos/depictio/depictio/releases/latest")
        assert call["headers"]["Accept"] == "application/vnd.github+json"
        assert call["headers"]["User-Agent"] == f"depictio/{CURRENT_STABLE}"
        assert github.timeout == settings.version_check.timeout_seconds
        assert view["update_available"] is True
        assert view["latest_version"] == "1.16.0"
        assert view["release_url"].endswith("/releases/tag/v1.16.0")
        assert view["published_at"] == "2026-03-04T05:06:07"
        assert view["last_error"] is None
        assert view["checked_at"] is not None

    def test_beta_lists_releases_and_picks_highest_non_draft(self, store, github, current):
        current(CURRENT_BETA)
        github.responses["list"] = FakeResponse(
            [
                _release("v1.15.1-b2", prerelease=True),
                _release("v9.9.9", draft=True),
                _release("v1.15.2-b1", prerelease=True),
                _release("nightly"),
                _release("v1.15.1"),
            ]
        )
        view = asyncio.run(vc.run_version_check(force=True))

        (call,) = github.calls
        assert call["url"].endswith("/repos/depictio/depictio/releases")
        assert call["params"] == {"per_page": 30}
        assert view["latest_version"] == "1.15.2-b1"
        assert view["update_available"] is True

    def test_running_the_latest_is_not_an_update(self, store, github, current):
        current(CURRENT_STABLE)
        github.responses["latest"] = FakeResponse(_release("v1.15.1"))
        assert asyncio.run(vc.run_version_check(force=True))["update_available"] is False

    def test_network_error_keeps_previous_latest_and_does_not_raise(self, store, github, current):
        current(CURRENT_STABLE)
        github.responses["latest"] = FakeResponse(_release("v1.16.0"))
        asyncio.run(vc.run_version_check(force=True))

        github.error = httpx.ConnectError("boom")
        view = asyncio.run(vc.run_version_check(force=True))
        assert view["last_error"] == "Could not reach GitHub"
        assert view["latest_version"] == "1.16.0"
        assert view["update_available"] is True

    def test_http_error_is_stored_short(self, store, github, current):
        current(CURRENT_STABLE)
        github.responses["latest"] = FakeResponse({}, status=403)
        view = asyncio.run(vc.run_version_check(force=True))
        assert "rate limit" in view["last_error"]
        assert view["latest_version"] is None

    def test_unparsable_tag_is_an_error_not_an_update(self, store, github, current):
        current(CURRENT_STABLE)
        github.responses["latest"] = FakeResponse(_release("nightly"))
        view = asyncio.run(vc.run_version_check(force=True))
        assert view["update_available"] is False
        assert view["last_error"]

    def test_unforced_run_respects_the_claim(self, store, github, current):
        current(CURRENT_STABLE)
        github.responses["latest"] = FakeResponse(_release("v1.16.0"))
        asyncio.run(vc.run_version_check())
        asyncio.run(vc.run_version_check())
        assert len(github.calls) == 1

    def test_forced_run_skips_the_claim_but_pushes_next_check_out(self, store, github, current):
        current(CURRENT_STABLE)
        github.responses["latest"] = FakeResponse(_release("v1.16.0"))
        asyncio.run(vc.run_version_check())
        before = store.find_one({"_id": "version_check"})["next_check_at"]
        asyncio.run(vc.run_version_check(force=True))
        assert len(github.calls) == 2
        after = store.find_one({"_id": "version_check"})["next_check_at"]
        assert after >= before


class TestViews:
    def test_admin_view_shape(self, store, current):
        current(CURRENT_STABLE)
        assert set(vc.admin_view()) == {
            "enabled",
            "env_enabled",
            "override",
            "locked_by_env",
            "interval_hours",
            "repository",
            "current_version",
            "update_available",
            "latest_version",
            "release_url",
            "published_at",
            "checked_at",
            "last_error",
        }
        assert set(vc.public_block()) == {
            "enabled",
            "locked_by_env",
            "update_available",
            "latest_version",
            "release_url",
            "published_at",
            "checked_at",
            "last_error",
        }

    def test_disabled_never_reports_an_update(self, store, github, current):
        current(CURRENT_STABLE)
        github.responses["latest"] = FakeResponse(_release("v1.16.0"))
        assert asyncio.run(vc.run_version_check(force=True))["update_available"] is True

        vc.set_override(False)
        view = vc.admin_view()
        assert view["enabled"] is False
        assert view["override"] is False
        assert view["update_available"] is False
        assert vc.public_block()["update_available"] is False
        # The stored answer is kept, so re-enabling shows it again immediately.
        assert view["latest_version"] == "1.16.0"
