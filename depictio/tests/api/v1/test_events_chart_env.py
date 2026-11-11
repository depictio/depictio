"""Helm chart: realtime events are opt-in and wired to this release's Redis."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[4]
CHART = ROOT / "helm-charts" / "depictio"


def _read(*parts: str) -> str:
    return CHART.joinpath(*parts).read_text()


def test_events_stay_off_unless_the_values_turn_them_on():
    env = yaml.safe_load(_read("values.yaml"))["backend"]["env"]
    assert env.get("DEPICTIO_EVENTS_ENABLED", "false") != "true"
    helper = _read("templates", "_helpers.tpl")
    assert (
        'eq (.Values.backend.env.DEPICTIO_EVENTS_ENABLED | default "false" | toString) "true"'
        in helper
    )


def test_the_events_redis_is_the_release_redis_not_the_code_default():
    """The code default host is "redis"; the release's service is "<release>-redis"."""
    helper = _read("templates", "_helpers.tpl")
    assert 'DEPICTIO_EVENTS_REDIS_HOST: {{ printf "%s-redis" .Release.Name | quote }}' in helper


def test_backend_and_worker_configmaps_both_get_the_events_env():
    """The worker publishes task and ingestion events; the API publishes the rest."""
    configmaps = _read("templates", "configmaps.yaml")
    assert configmaps.count('include "depictio.eventsEnv"') == 2
