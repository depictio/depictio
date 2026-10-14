"""The Python payload and the TypeScript shim must agree on `OfflineData`.

`_empty_data()` in embed.py and `interface OfflineData` in
`depictio/viewer/src/offline/mockApi.ts` are the same structure written twice, in
two languages, in two directories. Nothing links them, and a mismatch is invisible
on both sides: Python happily emits a bucket nobody reads, and the shim happily
declares one nobody fills. What surfaces instead is the *renderer* falling through
to the real `api.ts`, which fetches — and an embed's `connect-src 'none'` refuses
that, so the symptom is a CSP violation in a host page's console, three layers from
the cause. That is how the missing `schemas` bucket was found.

Parsing the interface with a regex is crude, but the alternative is a Node
toolchain in a Python test run, and the declaration is a flat list of `name: type;`
lines that a stricter parser would not read any differently.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from depictio.api.v1.services.export.embed import _empty_data

MOCK_API = (
    Path(__file__).resolve().parents[6] / "depictio" / "viewer" / "src" / "offline" / "mockApi.ts"
)


def _offline_data_fields() -> set[str]:
    """Top-level field names declared by `interface OfflineData`."""
    source = MOCK_API.read_text()
    match = re.search(r"export interface OfflineData \{(.*?)\n\}", source, re.DOTALL)
    assert match, f"could not locate `interface OfflineData` in {MOCK_API}"

    body = match.group(1)
    # Drop comments first, so a field name mentioned in prose is not read as one.
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
    body = re.sub(r"//.*", "", body)

    fields = set()
    depth = 0
    for line in body.splitlines():
        stripped = line.strip()
        # Only lines at brace depth 0 are top-level fields; `cards` nests a block.
        if depth == 0:
            declaration = re.match(r"^(\w+)\s*\??\s*:", stripped)
            if declaration:
                fields.add(declaration.group(1))
        depth += stripped.count("{") - stripped.count("}")
    return fields


class TestOfflineDataContract:
    def test_mock_api_is_where_we_think_it_is(self) -> None:
        """A moved file would make every assertion below vacuous."""
        assert MOCK_API.exists(), MOCK_API

    def test_python_and_typescript_declare_the_same_buckets(self) -> None:
        python_fields = set(_empty_data())
        typescript_fields = _offline_data_fields()

        assert python_fields == typescript_fields, (
            "OfflineData has drifted between _empty_data() (embed.py) and "
            "interface OfflineData (mockApi.ts).\n"
            f"  only in Python:     {sorted(python_fields - typescript_fields)}\n"
            f"  only in TypeScript: {sorted(typescript_fields - python_fields)}"
        )

    @pytest.mark.parametrize(
        "bucket",
        ["figures", "tables", "maps", "images", "multiqc", "unique", "specs", "schemas"],
    )
    def test_every_bucket_is_present_and_empty_by_default(self, bucket: str) -> None:
        """A missing key throws `no … payload for` at render time, not at build."""
        assert _empty_data()[bucket] == {}


class TestShimCoversWhatRenderersCall:
    """Every network-touching function a renderer calls must be shimmed.

    A function the shim does not override falls through to the real `api.ts` and
    fetches from inside a bundle whose CSP forbids it.
    """

    @pytest.mark.parametrize(
        "function_name",
        [
            "fetchUniqueValues",
            "fetchColumnRange",
            "fetchSpecs",
            "fetchPolarsSchema",
            "fetchAdvancedVizData",
            "fetchPhylogenyNewick",
            "renderFigure",
            "renderTable",
            "renderMultiQC",
        ],
    )
    def test_function_is_overridden_offline(self, function_name: str) -> None:
        source = MOCK_API.read_text()
        assert f"export async function {function_name}(" in source, (
            f"{function_name} is not overridden in mockApi.ts, so an embed calling it "
            "will fetch and be refused by its own connect-src 'none'"
        )
