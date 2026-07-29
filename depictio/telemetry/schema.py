"""The exact shape of every telemetry payload Depictio sends.

This module is the contract. ``docs/telemetry.md`` is generated from the field
descriptions here by ``scripts/gen_telemetry_docs.py`` and drift-checked in CI, so
what operators read is what actually goes over the wire — a documented payload
that can silently diverge from the real one is worse than no documentation.

Every field is either an enumerable string, a boolean, or a bucket label. There
are deliberately **no free-form string fields and no exact counts**: a schema that
cannot express a hostname, a path or a project name cannot leak one, which is a
stronger guarantee than sanitising at the call site. The one apparent exception,
:attr:`CliCommandProperties.command`, is constrained to the CLI's own command tree
by an allowlist rather than accepting whatever the user typed.
"""

from typing import Final

from pydantic import BaseModel, ConfigDict, Field

#: Event names. Kept as constants rather than an enum so they read cleanly at the
#: call sites and in the collector's own dashboards.
EVENT_INSTALL: Final[str] = "server_install"
EVENT_HEARTBEAT: Final[str] = "server_heartbeat"
EVENT_CLI_COMMAND: Final[str] = "cli_command"

ALL_EVENTS: Final[tuple[str, ...]] = (EVENT_INSTALL, EVENT_HEARTBEAT, EVENT_CLI_COMMAND)


class _StrictBase(BaseModel):
    """Reject unknown fields.

    ``extra="forbid"`` is a privacy control, not a style choice: it means a future
    change cannot bolt an ad-hoc key onto a payload without also declaring it here,
    where the docs generator and the payload-allowlist test will both see it.
    """

    model_config = ConfigDict(extra="forbid")


class CommonProperties(_StrictBase):
    """Properties present on every event, from both the server and the CLI."""

    depictio_version: str = Field(
        description="Depictio version reporting the event, e.g. `1.2.1`.",
    )
    deployment_kind: str = Field(
        description=(
            "How this Depictio was deployed: `helm` (our Helm chart), `kubernetes` "
            "(hand-rolled manifests, no chart), `docker-compose` (the production "
            "Compose file), `docker-compose-dev` (the dev Compose file), `docker`, "
            "`devcontainer` or `local`."
        ),
    )
    os: str = Field(description="Operating system family, e.g. `Linux`. Never the hostname.")
    arch: str = Field(description="CPU architecture, e.g. `x86_64` or `arm64`.")
    python_version: str = Field(description="Python version running Depictio, e.g. `3.11.9`.")


class UsageBuckets(_StrictBase):
    """Aggregate size of a deployment, as bucket labels — never exact counts.

    Sent only when ``DEPICTIO_TELEMETRY_INCLUDE_USAGE_METRICS`` is true. Each value
    is one of the labels in :data:`depictio.telemetry.buckets.LABELS`, or
    ``unknown`` if the count could not be computed.
    """

    users: str = Field(description="Number of user accounts, bucketed.")
    groups: str = Field(description="Number of groups, bucketed.")
    projects: str = Field(description="Number of projects, bucketed.")
    dashboards: str = Field(description="Number of dashboards, bucketed.")
    data_collections: str = Field(description="Number of data collections, bucketed.")
    workflows: str = Field(description="Number of workflows, bucketed.")
    runs: str = Field(description="Number of workflow runs, bucketed.")
    deltatables: str = Field(description="Number of Delta tables, bucketed.")
    active_users_7d: str = Field(
        description=(
            "Users active in the last 7 days, bucketed. `unknown` unless the "
            "operator has also enabled the local analytics subsystem."
        ),
    )
    component_types: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Bucketed count per dashboard component type (`figure`, `table`, "
            "`card`, …). Keys are Depictio's own component type names; no "
            "user-supplied string can appear here."
        ),
    )


class FeatureFlags(_StrictBase):
    """Which optional subsystems this deployment has switched on.

    Booleans only. The point is to learn which features are worth investing in,
    which needs no more resolution than on/off.
    """

    auth_single_user_mode: bool = Field(description="Running as a single-user personal instance.")
    auth_public_mode: bool = Field(description="Unauthenticated/public access enabled.")
    auth_demo_mode: bool = Field(description="Demo mode enabled.")
    analytics_enabled: bool = Field(description="Local (inbound) analytics subsystem enabled.")
    google_analytics_enabled: bool = Field(
        description="Google Analytics enabled for the frontend. The tracking ID is never sent.",
    )
    events_enabled: bool = Field(description="Real-time WebSocket/SSE events enabled.")
    monitoring_enabled: bool = Field(description="Admin log & task monitoring enabled.")
    dashboard_yaml_enabled: bool = Field(description="YAML dashboard sync enabled.")
    jbrowse_enabled: bool = Field(description="JBrowse integration enabled.")
    external_s3: bool = Field(
        description=(
            "True when object storage is outside the deployment's own network, i.e. "
            "something other than the bundled MinIO. A boolean only — the endpoint "
            "and bucket name are never sent."
        ),
    )


class ServerHeartbeatProperties(CommonProperties):
    """Payload for `server_install` and `server_heartbeat`.

    ``server_install`` fires exactly once per installation; ``server_heartbeat``
    fires at most once per UTC day per installation, however many workers or
    replicas are running.
    """

    boot_id: str = Field(
        description=(
            "Random ID regenerated on every process start. Lets a restart be "
            "distinguished from a second install, and makes a database restored "
            "into a second environment visible as such."
        ),
    )
    api_version: str = Field(description="Major API version served, e.g. `v1`.")
    install_age_days: int = Field(
        description=(
            "Whole days since this installation first reported. The only retention "
            "metric sent, and it needs no activity dates to compute."
        ),
    )
    workers: int = Field(description="Configured number of API worker processes.")
    features: FeatureFlags = Field(description="Optional subsystems switched on.")
    usage: UsageBuckets | None = Field(
        default=None,
        description="Bucketed deployment size. Absent when usage metrics are disabled.",
    )
    cli_versions_seen: list[str] = Field(
        default_factory=list,
        description=(
            "Distinct `depictio-cli` versions that talked to this instance recently, "
            "read from the CLI's request headers. Versions only — no host or user."
        ),
    )


class CliCommandProperties(CommonProperties):
    """Payload for `cli_command`, emitted once per `depictio-cli` invocation."""

    command: str = Field(
        description=(
            "The command path that ran, e.g. `data process` or `dashboard import`. "
            "Matched against the CLI's own command tree and dropped if it does not "
            "match, so arguments, file paths and values can never appear here."
        ),
    )
    succeeded: bool = Field(description="Whether the command exited without error.")
    duration_bucket: str = Field(
        description="How long the command took, bucketed (`<1s`, `1-10s`, `10-60s`, `1-10m`, `10m+`).",
    )
    is_ci: bool = Field(
        description=(
            "Whether an automated environment was detected. Always false in practice, "
            "since CI suppresses the send entirely; retained so the collector can "
            "prove that."
        ),
    )
    id_ephemeral: bool = Field(
        description=(
            "True when the anonymous CLI ID could not be persisted (read-only home "
            "directory), meaning this invocation counts as a new ID."
        ),
    )
