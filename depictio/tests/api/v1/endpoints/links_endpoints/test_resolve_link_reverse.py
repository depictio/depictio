"""``POST /links/{project_id}/resolve`` with ``reverse=True``.

Selection groups may walk a ``direct`` link from its target back to its source
(see ``_link_paths`` in ``depictio/api/v1/filter_links.py``). The endpoint
answers such a hop: the request's source is the link's target, the filter column
is read there, and the values come back for the link's source.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from depictio.api.v1.endpoints.links_endpoints import routes
from depictio.models.models.links import LinkResolutionRequest

pytestmark = pytest.mark.no_db

PROJECT_ID = "fcf60afdea2241b493b9c473"
LINK_ID = "6a19541e70f089f587c39c6a"
# The hub (one row per library) and the peak table it links out to.
DESIGN_DC = "6a19541470f089f587c39c64"
PEAKS_DC = "6a1954189fa2f2d1ffc39c76"


def _project(resolver: str = "direct", target_field: str | None = "sample") -> dict:
    """``sample_design.merged_library -> macs2_broad_peaks.sample``, as atacseq declares it."""
    return {
        "_id": PROJECT_ID,
        "links": [
            {
                "id": LINK_ID,
                "enabled": True,
                "source_dc_id": DESIGN_DC,
                "source_column": "merged_library",
                "target_dc_id": PEAKS_DC,
                "target_type": "table",
                "link_config": {"resolver": resolver, "target_field": target_field},
            }
        ],
    }


async def _resolve(project: dict, **request):
    with patch.object(routes, "_get_project_or_404", return_value=project):
        return await routes.resolve_link(
            request=LinkResolutionRequest(**request),
            project_id=PROJECT_ID,
            current_user=None,  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_reverse_reads_the_filter_column_on_the_link_target():
    translate = AsyncMock(return_value=["LIB1.mLb.clN", "LIB2.mLb.clN"])
    with patch.object(routes, "_translate_filter_values", translate):
        response = await _resolve(
            _project(),
            source_dc_id=PEAKS_DC,
            source_column="peak_id",
            filter_values=["peak_1", "peak_7"],
            target_dc_id=DESIGN_DC,
            reverse=True,
        )

    # The peak ids live on the peak table, so that is the table queried, for
    # the column the link joins on there (`target_field`), not the hub's name.
    translate.assert_awaited_once_with(
        source_dc_id=PEAKS_DC,
        filter_column="peak_id",
        filter_values=["peak_1", "peak_7"],
        link_column="sample",
    )
    assert response.resolved_values == ["LIB1.mLb.clN", "LIB2.mLb.clN"]
    assert response.link_id == LINK_ID
    assert response.resolver_used == "direct"
    assert response.source_count == 2


@pytest.mark.asyncio
async def test_reverse_on_the_join_column_passes_the_values_through():
    translate = AsyncMock()
    with patch.object(routes, "_translate_filter_values", translate):
        response = await _resolve(
            _project(),
            source_dc_id=PEAKS_DC,
            source_column="sample",
            filter_values=["LIB1.mLb.clN"],
            target_dc_id=DESIGN_DC,
            reverse=True,
        )
    translate.assert_not_awaited()
    assert response.resolved_values == ["LIB1.mLb.clN"]


@pytest.mark.asyncio
async def test_without_target_field_the_join_column_is_the_link_source_column():
    translate = AsyncMock()
    with patch.object(routes, "_translate_filter_values", translate):
        response = await _resolve(
            _project(target_field=None),
            source_dc_id=PEAKS_DC,
            source_column="merged_library",
            filter_values=["LIB1.mLb.clN"],
            target_dc_id=DESIGN_DC,
            reverse=True,
        )
    translate.assert_not_awaited()
    assert response.resolved_values == ["LIB1.mLb.clN"]


@pytest.mark.asyncio
async def test_only_direct_links_can_be_walked_in_reverse():
    # A sample_mapping link expands values one way; it has no inverse to walk.
    with pytest.raises(HTTPException) as exc:
        await _resolve(
            _project(resolver="sample_mapping"),
            source_dc_id=PEAKS_DC,
            source_column="sample",
            filter_values=["LIB1.mLb.clN"],
            target_dc_id=DESIGN_DC,
            reverse=True,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_the_same_request_without_reverse_finds_no_link():
    # Forward resolution is unchanged: nothing is declared from the peaks to the hub.
    with pytest.raises(HTTPException) as exc:
        await _resolve(
            _project(),
            source_dc_id=PEAKS_DC,
            source_column="sample",
            filter_values=["LIB1.mLb.clN"],
            target_dc_id=DESIGN_DC,
        )
    assert exc.value.status_code == 404
