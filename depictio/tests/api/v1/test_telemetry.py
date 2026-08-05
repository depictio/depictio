"""Tests for the server-side installation telemetry.

Two things here are load-bearing and should be treated as release blockers:

* ``TestPayloadContainsNothingIdentifying`` — the guarantee that lets telemetry
  default to enabled. It seeds a database with emails, project names and dashboard
  titles, then asserts none of them can appear in the payload.
* ``TestSendGuard`` — the guarantee that one installation reports once a day
  rather than once per gunicorn worker per Kubernetes replica.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mongomock import MongoClient

from depictio.api.v1.telemetry.cli_versions import (
    CLI_VERSIONS_DOC_ID,
    read_cli_versions,
    record_cli_version,
)
from depictio.api.v1.telemetry.guard import _guard_id, claim_send, has_sent, release_send
from depictio.api.v1.telemetry.identity import IDENTITY_DOC_ID, install_age_days
from depictio.telemetry.buckets import LABELS

# Values seeded into the fake database that must never reach a payload.
SECRET_EMAIL_STEM = "very-private-person"
SECRET_PROJECT = "CONFIDENTIAL-PATIENT-COHORT-2026"
SECRET_DASHBOARD = "Unpublished results, do not share"


@pytest.fixture
def telemetry_db():
    """A mongomock database patched over every collection telemetry reads."""
    client = MongoClient()
    db = client.test_db

    patches = {
        "telemetry_collection": db.telemetry,
        "users_collection": db.users,
        "groups_collection": db.groups,
        "projects_collection": db.projects,
        "dashboards_collection": db.dashboards,
        "data_collections_collection": db.data_collections,
        "workflows_collection": db.workflows,
        "runs_collection": db.runs,
        "deltatables_collection": db.deltatables,
    }

    with patch.multiple("depictio.api.v1.db", db=db, **patches):
        yield db
    client.close()


@pytest.fixture
def seeded_db(telemetry_db):
    """Populate the fake database with data that is deliberately sensitive."""
    telemetry_db.users.insert_many(
        [{"email": f"{SECRET_EMAIL_STEM}-{i}@hospital.invalid"} for i in range(37)]
    )
    telemetry_db.projects.insert_many([{"name": SECRET_PROJECT} for _ in range(3)])
    telemetry_db.dashboards.insert_many(
        [
            {
                "title": SECRET_DASHBOARD,
                "stored_metadata": [
                    {"component_type": "figure"},
                    {"component_type": "figure"},
                    {"component_type": "table"},
                ],
            }
            for _ in range(7)
        ]
    )
    return telemetry_db


class TestInstanceIdentity:
    def test_identity_is_shared_by_every_worker(self, telemetry_db):
        """Many workers racing must converge on one ID, not create one each."""
        from depictio.api.v1.telemetry.identity import get_or_create_instance_id

        ids = {get_or_create_instance_id()[0] for _ in range(12)}
        assert len(ids) == 1
        assert telemetry_db.telemetry.count_documents({"_id": IDENTITY_DOC_ID}) == 1

    def test_identity_survives_repeated_boots(self, telemetry_db):
        from depictio.api.v1.telemetry.identity import get_or_create_instance_id

        first, created_first = get_or_create_instance_id()
        second, created_second = get_or_create_instance_id()
        assert first == second
        assert created_first == created_second

    def test_install_age_days(self):
        assert install_age_days(datetime.now(timezone.utc)) == 0
        assert install_age_days(datetime.now(timezone.utc) - timedelta(days=9)) == 9

    def test_install_age_tolerates_naive_datetimes(self):
        """MongoDB round-trips datetimes as naive UTC; subtracting must not raise."""
        naive = datetime.utcnow() - timedelta(days=3)
        assert install_age_days(naive) == 3

    def test_negative_age_is_clamped(self):
        """A clock skew must not produce a negative age."""
        assert install_age_days(datetime.now(timezone.utc) + timedelta(days=5)) == 0


class TestSendGuard:
    def test_only_one_of_many_workers_may_send(self, telemetry_db):
        """The whole point: 12 processes, one heartbeat."""
        granted = [claim_send("server_heartbeat", daily=True) for _ in range(12)]
        assert sum(granted) == 1
        assert granted[0] is True

    def test_install_guard_is_once_per_installation_ever(self, telemetry_db):
        granted = [claim_send("server_install", daily=False) for _ in range(5)]
        assert sum(granted) == 1

    def test_has_sent_does_not_consume_the_guard(self, telemetry_db):
        """The admin preview reads this; it must not suppress the real send."""
        assert has_sent("server_heartbeat", daily=True) is False
        assert has_sent("server_heartbeat", daily=True) is False
        assert claim_send("server_heartbeat", daily=True) is True
        assert has_sent("server_heartbeat", daily=True) is True

    def test_a_new_day_gets_a_fresh_guard(self, telemetry_db):
        assert claim_send("server_heartbeat", daily=True) is True
        assert claim_send("server_heartbeat", daily=True) is False

        # Guard IDs are date-stamped, so tomorrow's ID is simply a different key.
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
        with patch(
            "depictio.api.v1.telemetry.guard._guard_id",
            return_value=f"send:server_heartbeat:{tomorrow}",
        ):
            assert claim_send("server_heartbeat", daily=True) is True

    def test_guard_declines_when_mongodb_is_unreachable(self, telemetry_db):
        """Failing closed is right: a missed heartbeat loses one point, a duplicate
        corrupts the installation count."""
        with patch.object(
            telemetry_db.telemetry, "insert_one", side_effect=RuntimeError("no mongo")
        ):
            assert claim_send("server_heartbeat", daily=True) is False

    def test_guard_documents_carry_an_expiry_field(self, telemetry_db):
        """The TTL index keys off this field; the identity document must lack it."""
        claim_send("server_heartbeat", daily=True)
        guard = telemetry_db.telemetry.find_one({"_id": {"$ne": IDENTITY_DOC_ID}})
        assert guard is not None
        assert "guard_expires_at" in guard

    def test_guard_expiry_is_in_the_future(self, telemetry_db):
        """The expiry must be a future timestamp, not the moment of writing.

        The TTL index is created with ``expireAfterSeconds=0``, which is MongoDB's
        expire-*at*-the-indexed-timestamp mode rather than "expire immediately".
        Writing ``now`` into the field therefore made every guard eligible for
        deletion the instant it was created, and the TTL monitor removed it within
        a minute — so ``server_install`` re-fired on each restart and heartbeats
        could repeat within a day, inflating the installation count this guard
        exists to keep honest.

        Asserting merely that the field is *present* cannot catch that, which is
        why this checks the value.
        """
        before = datetime.now(timezone.utc)
        claim_send("server_heartbeat", daily=True)

        guard = telemetry_db.telemetry.find_one({"_id": {"$ne": IDENTITY_DOC_ID}})
        assert guard is not None

        expires_at = guard["guard_expires_at"]
        # mongomock/pymongo round-trip datetimes as naive UTC.
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        assert expires_at > before, "guard would be deleted immediately by the TTL monitor"
        # Must also outlive a daily send interval, or a restart late in the day
        # could re-send after the guard had already been collected.
        assert expires_at - before >= timedelta(days=1)

    def test_the_install_guard_carries_no_expiry_at_all(self, telemetry_db):
        """The one guard that must survive the TTL sweep outright.

        ``guard_expires_at`` is what the TTL index keys off, so writing it on the
        undated install guard hands that document to the TTL monitor. A week later
        it is gone, the heartbeat loop re-claims it on its next pass, and
        ``server_install`` fires again — once per TTL period, for the life of the
        deployment. The installation count would then grow on its own, without a
        single new installation.

        Checking that the *daily* guard still carries the field matters just as
        much: both documents live in the same collection, and this field is the
        only thing that tells the TTL monitor them apart.
        """
        claim_send("server_install", daily=False)
        install_guard = telemetry_db.telemetry.find_one(
            {"_id": _guard_id("server_install", daily=False)}
        )
        assert install_guard is not None
        assert "guard_expires_at" not in install_guard

        claim_send("server_heartbeat", daily=True)
        heartbeat_guard = telemetry_db.telemetry.find_one(
            {"_id": _guard_id("server_heartbeat", daily=True)}
        )
        assert heartbeat_guard is not None
        assert "guard_expires_at" in heartbeat_guard

    def test_a_released_claim_can_be_taken_again(self, telemetry_db):
        """What a failed send has to leave behind.

        The claim is taken *before* the network call, so concurrent workers settle
        who sends without waiting on a collector. The cost is that a failed send
        would burn it — and for the install event, whose guard no longer expires,
        that means an installation that is never counted at all. Which is exactly
        the deployment whose first send hits a firewall.
        """
        assert claim_send("server_install", daily=False) is True
        assert claim_send("server_install", daily=False) is False

        release_send("server_install", daily=False)

        assert claim_send("server_install", daily=False) is True

    def test_releasing_never_raises_when_mongodb_is_unreachable(self, telemetry_db):
        with patch.object(
            telemetry_db.telemetry, "delete_one", side_effect=RuntimeError("no mongo")
        ):
            release_send("server_heartbeat", daily=True)


class TestSendReleasesTheClaimOnFailure:
    """The guard is only spent when the collector actually took the event."""

    @staticmethod
    def _send_once(*, accepted: bool) -> None:
        """Run ``_send`` end to end with the network and the config stubbed out."""
        from depictio.api.v1.telemetry.tasks import _send

        properties = MagicMock()
        properties.model_dump.return_value = {}

        stub_settings = MagicMock()
        # Debug mode returns before the send and must not be what this exercises.
        stub_settings.telemetry.debug = False

        with (
            patch("depictio.api.v1.telemetry.tasks.settings", stub_settings),
            patch(
                "depictio.api.v1.telemetry.tasks.build_heartbeat_properties",
                return_value=("anonymous-id", properties),
            ),
            patch(
                "depictio.api.v1.telemetry.tasks.acapture",
                new=AsyncMock(return_value=accepted),
            ),
        ):
            asyncio.run(_send("server_install", daily=False))

    def test_a_refused_send_leaves_the_claim_available(self, telemetry_db):
        self._send_once(accepted=False)
        assert claim_send("server_install", daily=False) is True, (
            "a collector outage cost this installation its install event permanently"
        )

    def test_an_accepted_send_spends_the_claim(self, telemetry_db):
        self._send_once(accepted=True)
        assert claim_send("server_install", daily=False) is False


class TestCliVersionRecording:
    @pytest.mark.parametrize("version", ["1.2.1", "1.3.0-b1", "2.0.0.dev1"])
    def test_plausible_versions_are_kept(self, telemetry_db, version):
        record_cli_version(version)
        assert version in read_cli_versions()

    @pytest.mark.parametrize(
        "hostile",
        [
            "../../etc/passwd",
            "$(whoami)",
            "not-a-version",
            "'; DROP COLLECTION telemetry; --",
            "<script>alert(1)</script>",
            "1.2.1 " + "A" * 500,
            "",
            None,
        ],
    )
    def test_hostile_headers_are_rejected(self, telemetry_db, hostile):
        """The header is attacker-controlled and ends up in an outbound payload."""
        record_cli_version(hostile)
        assert read_cli_versions() == []

    def test_stale_versions_age_out(self, telemetry_db):
        telemetry_db.telemetry.insert_one(
            {
                "_id": CLI_VERSIONS_DOC_ID,
                "versions": {"0_9_0": datetime.now(timezone.utc) - timedelta(days=400)},
            }
        )
        assert read_cli_versions() == []

    def test_result_is_capped(self, telemetry_db):
        for minor in range(20):
            record_cli_version(f"1.{minor}.0")
        assert len(read_cli_versions(limit=5)) == 5


class TestPayloadContainsNothingIdentifying:
    """The guarantee that justifies shipping telemetry enabled by default."""

    @pytest.fixture
    def payload(self, seeded_db):
        from depictio.api.v1.telemetry.payload import build_heartbeat_properties

        _instance_id, properties = build_heartbeat_properties()
        return properties.model_dump(mode="json", exclude_none=True)

    def test_no_seeded_secret_appears_anywhere(self, payload):
        blob = json.dumps(payload).lower()
        for forbidden in (
            SECRET_EMAIL_STEM,
            SECRET_PROJECT.lower(),
            SECRET_DASHBOARD.lower(),
            "hospital.invalid",
            "@",
        ):
            assert forbidden not in blob, f"{forbidden!r} leaked into the telemetry payload"

    def test_top_level_keys_are_an_exact_allowlist(self, payload):
        """A new field cannot be added without a deliberate change here.

        This is the tripwire: anyone extending the payload has to update this list,
        which forces the question "is this safe to send?" to be answered.
        """
        assert set(payload) == {
            "depictio_version",
            "deployment_kind",
            "os",
            "arch",
            "python_version",
            "boot_id",
            "api_version",
            "install_age_days",
            "workers",
            "features",
            "usage",
            "cli_versions_seen",
        }

    def test_all_feature_values_are_booleans(self, payload):
        assert all(isinstance(v, bool) for v in payload["features"].values())

    def test_all_usage_values_are_bucket_labels(self, payload):
        """Exact counts must never be transmitted — buckets only."""
        allowed = set(LABELS) | {"unknown"}
        usage = payload["usage"]
        component_types = usage.pop("component_types")
        assert set(usage.values()) <= allowed
        assert set(component_types.values()) <= allowed

    def test_counts_are_bucketed_not_exact(self, payload):
        """37 users, 3 projects and 7 dashboards were seeded."""
        assert payload["usage"]["users"] == "11-50"
        assert payload["usage"]["projects"] == "2-5"
        assert payload["usage"]["dashboards"] == "6-10"
        # 7 dashboards x 2 figures = 14, x 1 table = 7.
        assert payload["usage"]["component_types"] == {"figure": "11-50", "table": "6-10"}

    def test_active_users_is_unknown_without_local_analytics(self, payload):
        """Absent measurement must not masquerade as a measured zero."""
        assert payload["usage"]["active_users_7d"] == "unknown"

    def test_usage_omitted_when_operator_disables_it(self, seeded_db):
        from depictio.api.v1.telemetry.payload import build_heartbeat_properties

        with patch("depictio.api.v1.telemetry.payload.settings") as mock_settings:
            mock_settings.telemetry.include_usage_metrics = False
            mock_settings.telemetry.deployment_kind = None
            mock_settings.telemetry.replicas = None
            mock_settings.analytics.enabled = False
            mock_settings.fastapi.workers = 4
            _instance_id, properties = build_heartbeat_properties()

        assert properties.usage is None

    def test_a_failed_count_degrades_instead_of_losing_the_payload(self, seeded_db):
        """Knowing the install exists matters more than knowing its size."""
        from depictio.api.v1.telemetry.payload import build_heartbeat_properties

        with patch.object(
            seeded_db.users, "count_documents", side_effect=RuntimeError("mongo down")
        ):
            _instance_id, properties = build_heartbeat_properties()

        assert properties.usage is not None
        assert properties.usage.users == "unknown"
        assert properties.usage.projects == "2-5"


class TestKubernetesResourcesInPayload:
    """The Helm-only block: configured replicas and CPU/memory, never raw strings."""

    def test_absent_outside_helm(self, seeded_db):
        """No DEPICTIO_TELEMETRY_REPLICAS set means no kubernetes block at all."""
        from depictio.api.v1.telemetry.payload import build_heartbeat_properties

        _instance_id, properties = build_heartbeat_properties()
        assert properties.kubernetes is None

    def test_populated_and_parsed_when_helm_states_it(self, seeded_db):
        from depictio.api.v1.telemetry.payload import build_heartbeat_properties

        with patch("depictio.api.v1.telemetry.payload.settings") as mock_settings:
            mock_settings.telemetry.include_usage_metrics = False
            mock_settings.telemetry.deployment_kind = "helm"
            mock_settings.telemetry.replicas = 3
            mock_settings.telemetry.cpu_request = "0.5"
            mock_settings.telemetry.cpu_limit = "2"
            mock_settings.telemetry.memory_request = "1Gi"
            mock_settings.telemetry.memory_limit = "4Gi"
            mock_settings.analytics.enabled = False
            mock_settings.fastapi.workers = 4
            _instance_id, properties = build_heartbeat_properties()

        assert properties.kubernetes is not None
        assert properties.kubernetes.replicas == 3
        assert properties.kubernetes.cpu_request_millicores == 500
        assert properties.kubernetes.cpu_limit_millicores == 2000
        assert properties.kubernetes.memory_request_mib == 1024
        assert properties.kubernetes.memory_limit_mib == 4096

        blob = json.dumps(properties.model_dump(mode="json"))
        assert "0.5" not in blob, "the raw operator-typed CPU string must never reach the payload"
        assert "Gi" not in blob, "the raw operator-typed memory string must never reach the payload"

    def test_a_malformed_quantity_degrades_to_none_not_a_crash(self, seeded_db):
        from depictio.api.v1.telemetry.payload import build_heartbeat_properties

        with patch("depictio.api.v1.telemetry.payload.settings") as mock_settings:
            mock_settings.telemetry.include_usage_metrics = False
            mock_settings.telemetry.deployment_kind = "helm"
            mock_settings.telemetry.replicas = 1
            mock_settings.telemetry.cpu_request = "not-a-quantity"
            mock_settings.telemetry.cpu_limit = None
            mock_settings.telemetry.memory_request = None
            mock_settings.telemetry.memory_limit = None
            mock_settings.analytics.enabled = False
            mock_settings.fastapi.workers = 4
            _instance_id, properties = build_heartbeat_properties()

        assert properties.kubernetes is not None
        assert properties.kubernetes.replicas == 1
        assert properties.kubernetes.cpu_request_millicores is None


class TestSchemaForbidsUndeclaredFields:
    def test_extra_fields_are_rejected(self):
        """``extra="forbid"`` is a privacy control, not a style preference.

        It stops a future change bolting an ad-hoc key onto a payload without it
        passing through the schema, the docs generator and the allowlist test.
        """
        from pydantic import ValidationError

        from depictio.telemetry.schema import CliCommandProperties

        with pytest.raises(ValidationError):
            CliCommandProperties(
                depictio_version="1.2.1",
                deployment_kind="local",
                os="Linux",
                arch="x86_64",
                python_version="3.11.9",
                command="data process",
                succeeded=True,
                duration_bucket="<1s",
                is_ci=False,
                id_ephemeral=False,
                hostname="leaky-server-01",
            )


class TestShippedDefaultsRouteToTheProject:
    """The server must reach Depictio's own collector with no env overrides.

    An empty default would leave every deployment permanently silent while every
    other test still passed, so this is asserted explicitly.
    """

    def test_settings_default_is_the_project_token(self):
        from depictio.api.v1.configs.settings_models import TelemetryConfig
        from depictio.telemetry.constants import DEFAULT_API_KEY, DEFAULT_ENDPOINT

        field = TelemetryConfig.model_fields["api_key"]
        assert field.default == DEFAULT_API_KEY
        assert DEFAULT_API_KEY.startswith("phc_")
        assert TelemetryConfig.model_fields["endpoint"].default == DEFAULT_ENDPOINT

    def test_endpoint_is_the_eu_region(self):
        """EU keeps event data in the EEA; a US host would silently drop
        events for an EU-region project anyway."""
        from depictio.telemetry.constants import DEFAULT_ENDPOINT

        assert DEFAULT_ENDPOINT == "https://eu.i.posthog.com/i/v0/e/"

    def test_server_and_cli_share_one_project(self):
        """Two different tokens would split the counts across two projects."""
        from depictio.api.v1.configs.settings_models import TelemetryConfig
        from depictio.cli.cli.utils.telemetry import _DEFAULT_API_KEY

        assert TelemetryConfig.model_fields["api_key"].default == _DEFAULT_API_KEY
