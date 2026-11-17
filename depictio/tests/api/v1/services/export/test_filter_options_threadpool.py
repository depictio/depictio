"""The export's categorical options call the (synchronous) unique-values handler.

``get_unique_values`` runs in the thread pool, so a caller must not ``await`` it
directly: that raises ``TypeError`` once the handler returns a plain dict.
"""

from __future__ import annotations

import asyncio

from bson import ObjectId

from depictio.api.v1.endpoints.deltatables_endpoints import routes
from depictio.api.v1.services.export import filter_options


def test_categorical_options_run_the_sync_handler(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_unique_values(data_collection_id, column, limit, current_user, **_):
        seen.update(column=column, limit=limit)
        return {"column": column, "values": ["b", "a"]}

    monkeypatch.setattr(routes, "get_unique_values", fake_unique_values)

    result = asyncio.run(
        filter_options._categorical_options(str(ObjectId()), "locality", "select", "user")
    )

    assert result is not None
    assert result["values"] == ["b", "a"]
    assert seen["column"] == "locality"
    assert seen["limit"] == filter_options.MAX_OPTIONS + 1
