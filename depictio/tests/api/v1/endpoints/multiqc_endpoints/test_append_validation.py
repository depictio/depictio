"""An append validates the set that replaces the old reports (#1397 CI)."""


class TestAppendValidatesTheReplacingSet:
    """An append reprocesses the old reports with the new ones: the new rows
    replace the old, so the old rows must not count as other reports."""

    def _report(self, _id: str, name: str, samples: list[str]) -> dict:
        return {"_id": _id, "report_name": name, "metadata": {"samples": samples}}

    def test_old_rows_are_left_out(self):
        from depictio.api.v1.endpoints.multiqc_endpoints.utils import _reports_replacing

        old = [
            self._report("o1", "MultiQC Report 1", ["A1"]),
            self._report("o2", "MultiQC Report 2", ["B1"]),
        ]
        # The reprocess numbered the files in another order.
        new = [
            self._report("n1", "MultiQC Report 1", ["B1"]),
            self._report("n2", "MultiQC Report 2", ["C1"]),
            self._report("n3", "MultiQC Report 3", ["A1"]),
        ]
        kept = _reports_replacing(old + new, {"o1", "o2"})
        assert [r["_id"] for r in kept] == ["n1", "n2", "n3"]

    def test_nothing_new_keeps_the_old_set(self):
        from depictio.api.v1.endpoints.multiqc_endpoints.utils import _reports_replacing

        old = [self._report("o1", "MultiQC Report 1", ["A1"])]
        assert _reports_replacing(old, {"o1"}) == old
