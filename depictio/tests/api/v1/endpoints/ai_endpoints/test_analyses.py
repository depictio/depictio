"""AnalysisReport persistence and the evidence gate on findings.

The findings validator is the load-bearing part: a claim with no executed
evidence behind it must be dropped, not rendered with a caveat.
"""

from __future__ import annotations

import mongomock
import pytest

from depictio.api.v1.endpoints.ai_endpoints import analyses
from depictio.api.v1.endpoints.ai_endpoints.schemas import ExecutionStep, Finding


@pytest.fixture()
def steps() -> list[ExecutionStep]:
    return [
        ExecutionStep(code="df.height", output="100", status="success"),
        ExecutionStep(code="df.bad()", output="BlockedByPolicy", status="error"),
        ExecutionStep(code="df.mean()", output="12.5", status="success"),
    ]


class TestParseFindings:
    def test_valid_findings_pass(self, steps):
        warnings: list[str] = []
        out = analyses.parse_findings(
            [{"claim": "100 rows", "evidence_step_ids": [0], "confidence": "high"}],
            steps,
            warnings,
        )
        assert len(out) == 1
        assert out[0].claim == "100 rows"
        assert warnings == []

    def test_empty_evidence_is_dropped_and_recorded(self, steps):
        warnings: list[str] = []
        out = analyses.parse_findings(
            [{"claim": "trust me", "evidence_step_ids": []}], steps, warnings
        )
        assert out == []
        assert any("trust me" in w for w in warnings)

    def test_missing_evidence_key_is_dropped(self, steps):
        warnings: list[str] = []
        out = analyses.parse_findings([{"claim": "no evidence key"}], steps, warnings)
        assert out == []
        assert len(warnings) == 1

    def test_citing_a_failed_step_is_dropped(self, steps):
        # Step 1 errored: it produced no data, so it proves nothing.
        warnings: list[str] = []
        out = analyses.parse_findings(
            [{"claim": "based on the blocked step", "evidence_step_ids": [1]}],
            steps,
            warnings,
        )
        assert out == []
        assert any("failed steps" in w for w in warnings)

    def test_citing_a_nonexistent_step_is_dropped(self, steps):
        warnings: list[str] = []
        out = analyses.parse_findings(
            [{"claim": "step 9 says so", "evidence_step_ids": [9]}], steps, warnings
        )
        assert out == []

    def test_mixed_batch_keeps_the_valid_ones(self, steps):
        warnings: list[str] = []
        out = analyses.parse_findings(
            [
                {"claim": "good", "evidence_step_ids": [0, 2]},
                {"claim": "bad", "evidence_step_ids": []},
            ],
            steps,
            warnings,
        )
        assert [f.claim for f in out] == ["good"]
        assert len(warnings) == 1

    def test_non_list_payload(self, steps):
        warnings: list[str] = []
        assert analyses.parse_findings("nonsense", steps, warnings) == []
        assert warnings  # recorded, not silent

    def test_finding_model_rejects_empty_evidence_directly(self):
        with pytest.raises(Exception):
            Finding(claim="x", evidence_step_ids=[])


class TestPersistence:
    @pytest.fixture()
    def collection(self, monkeypatch):
        coll = mongomock.MongoClient().db.ai_analyses
        monkeypatch.setattr(analyses, "_collection", lambda: coll)
        return coll

    def test_round_trip(self, collection):
        report = analyses.new_report("dash-1", "why is depth bimodal?", "test-model")
        report.steps.append(ExecutionStep(code="df.height", output="100", status="success"))
        report.status = "complete"
        analyses.save(report)

        loaded = analyses.get(report.id)
        assert loaded is not None
        assert loaded.dashboard_id == "dash-1"
        assert loaded.steps[0].output == "100"
        assert loaded.status == "complete"

    def test_save_is_upsert_not_append(self, collection):
        report = analyses.new_report("dash-1", "q", "m")
        analyses.save(report)  # running
        report.status = "complete"
        analyses.save(report)  # final
        assert collection.count_documents({}) == 1
        loaded = analyses.get(report.id)
        assert loaded is not None and loaded.status == "complete"

    def test_latest_for_dashboard_newest_first(self, collection):
        for i in range(3):
            r = analyses.new_report("dash-1", f"q{i}", "m")
            r.created_at = f"2026-08-0{i + 1}T00:00:00+00:00"
            analyses.save(r)
        analyses.save(analyses.new_report("other-dash", "q", "m"))

        out = analyses.latest_for_dashboard("dash-1")
        assert [r.prompt for r in out] == ["q2", "q1", "q0"]

    def test_get_unknown_id(self, collection):
        assert analyses.get("nope") is None
