"""Offline unit tests for scripts/check_deployment.py (no network: the client is faked)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "check_deployment.py"


@pytest.fixture(scope="module")
def cd() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_deployment_under_test", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _bar(n: int = 3) -> dict:
    return {
        "figure": {
            "data": [{"type": "bar", "x": list(range(n)), "y": list(range(n))}],
            "layout": {},
        },
        "metadata": {},
    }


def _error_figure(message: str) -> dict:
    return {
        "figure": {
            "data": [{"type": "scatter", "x": None, "y": None}],
            "layout": {"annotations": [{"text": f"⚠️ {message}"}]},
        },
        "metadata": {"error": message},
    }


def _figure_check(cd: ModuleType, payload: dict):
    check = cd.Check(
        dashboard_id="d",
        dashboard_title="D",
        family_title="F",
        index="fig",
        component_type="figure",
        validate="figure",
    )
    check.reply = cd.Reply(status=200, payload=payload)
    return check


# --------------------------------------------------------------------------- #
# Figure payloads
# --------------------------------------------------------------------------- #


def test_figure_with_points_passes(cd):
    check = _figure_check(cd, _bar())
    assert cd.classify(check, None) == "OK"


def test_code_error_inside_a_200_is_a_failure(cd):
    check = _figure_check(
        cd,
        _error_figure("Code execution error: Execution error: name '_inplacevar_' is not defined"),
    )
    assert cd.classify(check, None) == "FIGURE_ERROR"
    assert "_inplacevar_" in check.reason
    assert "FIGURE_ERROR" not in cd.WARNING and "FIGURE_ERROR" not in cd.PASSING


def test_validation_error_is_a_failure(cd):
    message = (
        "Code execution error: ❌ Code validation failed: Preprocessing creates variables, "
        "but fig line doesn't use any dataframe"
    )
    check = _figure_check(cd, _error_figure(message))
    assert cd.classify(check, None) == "FIGURE_ERROR"


def test_error_annotation_without_metadata_is_a_failure(cd):
    payload = _error_figure("Error: boom")
    payload["metadata"] = {}
    check = _figure_check(cd, payload)
    assert cd.classify(check, None) == "FIGURE_ERROR"


def test_figure_without_traces_is_empty_with_a_count(cd):
    check = _figure_check(cd, {"figure": {"data": [], "layout": {}}, "metadata": {}})
    assert cd.classify(check, None) == "EMPTY_RESULT"
    assert check.note == "no traces"


def test_traces_without_points_are_empty_with_a_count(cd):
    payload = {
        "figure": {
            "data": [
                {"type": "bar", "x": [], "y": []},
                {"type": "scatter", "x": [None], "y": [None]},
            ],
            "layout": {"annotations": [{"text": "No valid data found"}]},
        },
        "metadata": {},
    }
    check = _figure_check(cd, payload)
    assert cd.classify(check, None) == "EMPTY_RESULT"
    assert "2 trace(s), 0 plotted points" in check.note
    assert "No valid data found" in check.note


def test_legend_dummy_traces_do_not_hide_an_empty_chart_but_do_not_break_a_full_one(cd):
    payload = _bar()
    payload["figure"]["data"].append({"type": "scatter", "x": [None], "y": [None]})
    assert cd.classify(_figure_check(cd, payload), None) == "OK"


@pytest.mark.parametrize(
    ("trace", "expected"),
    [
        ({"type": "heatmap", "z": [[1, 2], [3, 4]]}, 4),
        ({"type": "heatmap", "z": [[], []]}, 0),
        ({"type": "sankey", "link": {"value": [1, 2]}}, 2),
        ({"type": "sankey", "link": {"value": []}}, 0),
        ({"type": "indicator"}, 1),
        ({"type": "pie", "values": [5, 6]}, 2),
        ({"type": "scatter", "x": {"dtype": "f8", "bdata": "AAAA"}}, 1),
    ],
)
def test_trace_points(cd, trace, expected):
    assert cd.trace_points(trace) == expected


# --------------------------------------------------------------------------- #
# Compute jobs
# --------------------------------------------------------------------------- #


def _compute_check(cd: ModuleType, kind: str, payload: dict):
    check = cd.Check(
        dashboard_id="d",
        dashboard_title="D",
        family_title="F",
        index="hm",
        component_type="advanced_viz",
        subtype=kind,
        validate="compute",
    )
    check.reply = cd.Reply(status=200, payload=payload)
    return check


def test_failed_job_reports_the_worker_error(cd):
    check = _compute_check(
        cd, "complex_heatmap", {"status": "failed", "error": "float division by zero"}
    )
    assert cd.classify(check, None) == "COMPUTE_FAILED"
    assert "float division by zero" in check.reason
    assert "COMPUTE_FAILED" not in cd.WARNING


def test_unfinished_job_is_a_warning(cd):
    check = _compute_check(cd, "upset_plot", {"status": "pending"})
    assert cd.classify(check, None) == "COMPUTE_TIMEOUT"
    assert "COMPUTE_TIMEOUT" in cd.WARNING


def test_finished_job_with_a_figure_passes(cd):
    done = {"status": "done", "result": {"figure": _bar(5)["figure"], "row_count": 5}}
    assert cd.classify(_compute_check(cd, "complex_heatmap", done), None) == "OK"


def test_finished_job_over_zero_rows_is_empty(cd):
    done = {"status": "done", "result": {"figure": _bar()["figure"], "row_count": 0}}
    check = _compute_check(cd, "upset_plot", done)
    assert cd.classify(check, None) == "EMPTY_RESULT"


def test_finished_embedding_without_samples_is_empty(cd):
    done = {"status": "done", "result": {"sample_ids": [], "dim_1": [], "dim_2": []}}
    assert cd.classify(_compute_check(cd, "embedding", done), None) == "EMPTY_RESULT"


class FakeClient:
    """Answers a poll sequence for one job id."""

    def __init__(self, answers: list[dict]) -> None:
        self.answers = list(answers)
        self.calls: list[tuple[str, str]] = []

    def call(self, method, path, body=None):
        self.calls.append((method, path))
        return _reply(self.answers.pop(0))


def _reply(payload):
    # Late import keeps the helper usable without the fixture.
    spec = sys.modules["check_deployment_under_test"]
    return spec.Reply(status=200, payload=payload)


def test_poll_job_follows_the_job_to_completion(cd, monkeypatch):
    monkeypatch.setattr(cd.time, "sleep", lambda _s: None)
    client = FakeClient([{"status": "pending"}, {"status": "failed", "error": "ZeroDivisionError"}])
    first = cd.Reply(status=200, payload={"job_id": "abc", "status": "pending"})
    final = cd.poll_job(client, "/advanced_viz/compute_complex_heatmap", first, timeout=30)
    assert final.payload["status"] == "failed"
    assert client.calls[0] == ("GET", "/advanced_viz/compute_complex_heatmap/abc")


def test_poll_job_keeps_a_cached_terminal_answer(cd):
    client = FakeClient([])
    first = cd.Reply(status=200, payload={"job_id": "abc", "status": "done", "result": {}})
    assert cd.poll_job(client, "/x", first, timeout=1) is first
    assert client.calls == []


def test_poll_job_passes_an_http_error_through(cd):
    client = FakeClient([])
    failed = cd.Reply(status=400, payload=None, detail="bad")
    assert cd.poll_job(client, "/x", failed, timeout=1) is failed


def test_poll_job_gives_up_at_the_budget(cd, monkeypatch):
    monkeypatch.setattr(cd.time, "sleep", lambda _s: None)
    ticks = iter([0.0, 0.0, 5.0, 10.0, 99.0, 99.0, 99.0])
    monkeypatch.setattr(cd.time, "monotonic", lambda: next(ticks))
    client = FakeClient([{"status": "pending"}] * 5)
    first = cd.Reply(status=200, payload={"job_id": "abc", "status": "pending"})
    final = cd.poll_job(client, "/x", first, timeout=8)
    assert final.payload["status"] == "pending"


# --------------------------------------------------------------------------- #
# Planning
# --------------------------------------------------------------------------- #


def _dash(*components: dict) -> dict:
    return {"dashboard_id": "d1", "title": "D", "stored_metadata": list(components)}


def _viz(kind: str, **config) -> dict:
    return {
        "index": f"{kind}-1",
        "component_type": "advanced_viz",
        "viz_kind": kind,
        "wf_id": "wf",
        "dc_id": "dc",
        "config": config,
    }


def test_default_plan_has_no_compute_probe(cd):
    checks = cd.plan_checks(
        _dash(_viz("coverage_track", chromosome_col="c", position_col="p")), "F"
    )
    assert [c.verdict for c in checks] == ["NOT_PROBED"]
    assert not any(c.poll_path for c in checks)


def test_dispatch_plan_adds_the_compute_probe(cd):
    dash = _dash(
        _viz("complex_heatmap", index_column="gene", value_columns=["a", "b"]),
        _viz("coverage_track", chromosome_col="c", position_col="p", value_col="v"),
        _viz("sankey", step_cols=["a", "b", "c"], depth=2),
        _viz("upset_plot", set_columns=["a", "b"]),
        _viz("embedding", compute_method="umap", sample_id_col="s"),
    )
    checks = cd.plan_checks(dash, "F", dispatch_compute=True)
    compute = {c.subtype: c for c in checks if c.poll_path}
    assert set(compute) == {
        "complex_heatmap",
        "coverage_track",
        "sankey",
        "upset_plot",
        "embedding",
    }
    assert compute["sankey"].body["step_cols"] == ["a", "b"]
    assert compute["embedding"].body["params"]["n_neighbors"] == 15
    assert compute["complex_heatmap"].path == "/advanced_viz/compute_complex_heatmap"
    # coverage_track is no longer left unprobed
    assert not any(c.verdict == "NOT_PROBED" for c in checks)


def test_embedding_with_precomputed_coordinates_is_not_dispatched(cd):
    checks = cd.plan_checks(_dash(_viz("embedding", sample_id_col="s")), "F", dispatch_compute=True)
    assert not any(c.poll_path for c in checks)


def test_sankey_needs_two_steps_to_dispatch(cd):
    checks = cd.plan_checks(_dash(_viz("sankey", step_cols=["a"])), "F", dispatch_compute=True)
    assert not any(c.poll_path for c in checks)
