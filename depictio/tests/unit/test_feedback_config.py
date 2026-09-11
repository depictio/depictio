"""The opt-in dashboard feedback link, as the frontend receives it."""

from __future__ import annotations

import pytest

from depictio.api.v1.configs.settings_models import FeedbackConfig


def test_off_by_default() -> None:
    """A deployment that set nothing must not grow a button that goes nowhere."""
    config = FeedbackConfig()
    assert config.enabled is False
    assert config.url is None
    assert config.is_configured is False


@pytest.mark.parametrize(
    ("enabled", "url"),
    [
        # Enabled but pointed nowhere: the flag alone renders no link.
        (True, None),
        (True, ""),
        # Pointed somewhere but not enabled: the URL alone renders no link.
        (False, "https://example.org/feedback"),
    ],
)
def test_half_configured_is_not_configured(enabled: bool, url: str | None) -> None:
    assert FeedbackConfig(enabled=enabled, url=url).is_configured is False


def test_fully_configured() -> None:
    config = FeedbackConfig(enabled=True, url="https://example.org/feedback", label="Tell us")
    assert config.is_configured is True
    assert config.label == "Tell us"


def test_reads_its_env_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEPICTIO_FEEDBACK_ENABLED", "true")
    monkeypatch.setenv("DEPICTIO_FEEDBACK_URL", "https://example.org/f?d={dashboard}")
    monkeypatch.setenv("DEPICTIO_FEEDBACK_LABEL", "Feedback")

    config = FeedbackConfig()

    assert config.is_configured is True
    # The template reaches the client verbatim — substitution happens there,
    # where the dashboard and tab on screen are known.
    assert config.url == "https://example.org/f?d={dashboard}"
