"""An embedded `interactive` control must arrive with its value universe.

The bug this guards: `_add_interactive` called `load_deltatable_lite` without
`init_data`, so the loader fell through to a deprecated in-process HTTP call it has
no token for. The resulting exception was swallowed into `unique: []`, and the
export returned 200 carrying a control with an empty dropdown — a widget that looks
fine in a screenshot and is useless in a page.

Two properties are asserted, and the second is the important one: the values must be
*read*, and a failure to read them must not be silent.
"""

from __future__ import annotations

from unittest.mock import patch

import polars as pl
import pytest

from depictio.api.v1.services.export.delta_location import init_data_for
from depictio.api.v1.services.export.embed import (
    _synthetic_dc_id,
    build_component_embed_payload,
)

DASHBOARD_DOC = {"dashboard_id": "d1", "project_id": "p1", "title": "T"}
DC_ID = "507f1f77bcf86cd799439055"
DELTA_LOCATION = "s3://depictio-bucket/507f1f77bcf86cd799439055"


def _control(**extra) -> dict:
    return {
        "index": "cmp-1",
        "component_type": "interactive",
        "title": "Sample ID",
        "wf_id": "507f1f77bcf86cd799439066",
        "dc_id": DC_ID,
        "interactive_component_type": "MultiSelect",
        "column_name": "sample",
        **extra,
    }


async def _build(component: dict) -> dict:
    return await build_component_embed_payload(
        dashboard_doc=DASHBOARD_DOC,
        component=component,
        theme="light",
        filters=[],
        access_token=None,
        current_user=object(),
    )


class TestInitDataResolution:
    """`init_data_for` is the seam that keeps the loader off its legacy HTTP path."""

    def test_prefers_the_components_own_snapshot_without_querying(self) -> None:
        with patch("depictio.api.v1.db.deltatables_collection") as collection:
            init_data = init_data_for(DC_ID, {"delta_location": DELTA_LOCATION})
        assert init_data[DC_ID]["delta_location"] == DELTA_LOCATION
        collection.find_one.assert_not_called()

    def test_falls_back_to_the_deltatables_collection(self) -> None:
        """Stored metadata predating `delta_location` still has to resolve."""
        with patch(
            "depictio.api.v1.db.deltatables_collection.find_one",
            return_value={"delta_table_location": DELTA_LOCATION},
        ):
            init_data = init_data_for(DC_ID, {})
        assert init_data[DC_ID]["delta_location"] == DELTA_LOCATION

    def test_unmaterialised_dc_yields_no_hint(self) -> None:
        with patch("depictio.api.v1.db.deltatables_collection.find_one", return_value=None):
            assert init_data_for(DC_ID, {}) == {}


class TestInteractivePayload:
    @pytest.mark.asyncio
    async def test_control_carries_the_columns_distinct_values(self) -> None:
        frame = pl.DataFrame({"sample": ["s2", "s1", "s2"]})
        with (
            patch(
                "depictio.api.v1.endpoints.deltatables_endpoints.routes.specs",
                return_value={},
            ),
            patch(
                "depictio.api.v1.db.deltatables_collection.find_one",
                return_value={"delta_table_location": DELTA_LOCATION},
            ),
            patch(
                "depictio.api.v1.deltatables_utils.load_deltatable_lite",
                return_value=frame,
            ) as load,
        ):
            payload = await _build(_control())

        key = f"{_synthetic_dc_id('cmp-1')}::sample"
        assert payload["data"]["unique"][key] == ["s1", "s2"], (
            "the MultiSelect renders this list; empty means an unusable control"
        )
        # The regression itself: omit init_data and the loader tries to make an
        # authenticated HTTP call that fails inside the export request.
        assert load.call_args.kwargs["init_data"][DC_ID]["delta_location"] == DELTA_LOCATION

    @pytest.mark.asyncio
    async def test_unmaterialised_dc_does_not_reach_the_legacy_loader(self) -> None:
        """No Delta table is an empty universe, but it must not be found out by
        making a call that cannot succeed."""
        with (
            patch(
                "depictio.api.v1.endpoints.deltatables_endpoints.routes.specs",
                return_value={},
            ),
            patch("depictio.api.v1.db.deltatables_collection.find_one", return_value=None),
            patch("depictio.api.v1.deltatables_utils.load_deltatable_lite") as load,
        ):
            payload = await _build(_control())

        key = f"{_synthetic_dc_id('cmp-1')}::sample"
        assert payload["data"]["unique"][key] == []
        load.assert_not_called()
