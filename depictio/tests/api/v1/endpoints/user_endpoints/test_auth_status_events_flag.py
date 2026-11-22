"""`GET /auth/me/optional` tells the viewer whether the realtime WebSocket exists.

With events off the `/events/ws` route is not mounted, so a viewer that tried it
anyway would retry a refused handshake for as long as the page stays open.
"""

import pytest

from depictio.api.v1.endpoints.user_endpoints import routes


@pytest.mark.parametrize("enabled", [True, False])
def test_status_reports_the_events_switch(test_client, monkeypatch, enabled):
    monkeypatch.setattr(routes.settings.events, "enabled", enabled)
    response = test_client.get("/depictio/api/v1/auth/me/optional")
    assert response.status_code == 200
    assert response.json()["events_enabled"] is enabled
