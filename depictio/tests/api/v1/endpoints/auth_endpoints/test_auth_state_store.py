"""Unit tests for the shared one-shot auth state store (SAML request IDs)."""

from unittest.mock import MagicMock, patch

from depictio.api.v1.endpoints.auth_endpoints import state_store

_NO_REDIS = patch(
    "depictio.api.v1.endpoints.auth_endpoints.state_store.get_shared_redis_client",
    return_value=None,
)


class TestInMemoryFallback:
    """Behavior when Redis is unavailable — in-process one-shot store."""

    def setup_method(self):
        state_store._local_states.clear()

    def test_store_and_consume_round_trip(self):
        with _NO_REDIS:
            state_store.store_auth_state("oauth", "abc", value="/dashboards")
            assert state_store.consume_auth_state("oauth", "abc") == "/dashboards"

    def test_consume_is_one_shot(self):
        with _NO_REDIS:
            state_store.store_auth_state("oauth", "abc")
            assert state_store.consume_auth_state("oauth", "abc") == "1"
            assert state_store.consume_auth_state("oauth", "abc") is None

    def test_unknown_key_returns_none(self):
        with _NO_REDIS:
            assert state_store.consume_auth_state("oauth", "never-stored") is None

    def test_empty_key_returns_none(self):
        with _NO_REDIS:
            assert state_store.consume_auth_state("saml", "") is None

    def test_kinds_are_isolated(self):
        with _NO_REDIS:
            state_store.store_auth_state("oauth", "abc")
            assert state_store.consume_auth_state("saml", "abc") is None
            assert state_store.consume_auth_state("oauth", "abc") == "1"

    def test_expired_entry_returns_none(self):
        with _NO_REDIS:
            state_store.store_auth_state("oauth", "abc", ttl_seconds=600)
            with patch(
                "depictio.api.v1.endpoints.auth_endpoints.state_store.time.monotonic",
                return_value=state_store._local_states[("oauth", "abc")][1] + 1,
            ):
                assert state_store.consume_auth_state("oauth", "abc") is None


class TestRedisPath:
    """Behavior with a (mocked) Redis client — shared across workers."""

    def setup_method(self):
        state_store._local_states.clear()

    def test_store_uses_set_nx_ex(self):
        client = MagicMock()
        with patch(
            "depictio.api.v1.endpoints.auth_endpoints.state_store.get_shared_redis_client",
            return_value=client,
        ):
            state_store.store_auth_state("oauth", "abc", value="v", ttl_seconds=600)
        client.set.assert_called_once_with("depictio:authstate:oauth:abc", "v", ex=600, nx=True)

    def test_consume_uses_getdel(self):
        client = MagicMock()
        client.getdel.return_value = "v"
        with patch(
            "depictio.api.v1.endpoints.auth_endpoints.state_store.get_shared_redis_client",
            return_value=client,
        ):
            assert state_store.consume_auth_state("saml", "id_1") == "v"
        client.getdel.assert_called_once_with("depictio:authstate:saml:id_1")

    def test_redis_error_falls_back_to_local(self):
        client = MagicMock()
        client.set.side_effect = ConnectionError("redis down")
        client.getdel.side_effect = ConnectionError("redis down")
        with patch(
            "depictio.api.v1.endpoints.auth_endpoints.state_store.get_shared_redis_client",
            return_value=client,
        ):
            state_store.store_auth_state("oauth", "abc", value="v")
            assert state_store.consume_auth_state("oauth", "abc") == "v"
