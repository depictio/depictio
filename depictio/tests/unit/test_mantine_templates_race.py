import copy
import threading
import time
import types

import plotly.io as pio
import pytest

from depictio.api.v1.services.figure import mantine_templates as mt


@pytest.fixture
def fresh_templates(monkeypatch):
    """A cold process: vanilla templates registered, no brand patch applied yet."""
    mt._ensure_base_templates()
    saved = {name: pio.templates[name] for name in mt._TEMPLATE_SCHEMES}
    monkeypatch.setattr(mt, "_vanilla", {})
    monkeypatch.setattr(mt, "_applied_key", mt._UNSET)
    theme = mt._effective_theme()
    monkeypatch.setattr(mt, "_effective_theme", lambda: theme)
    yield
    for name, template in saved.items():
        pio.templates[name] = template


def test_concurrent_first_renders_do_not_see_a_half_filled_cache(fresh_templates, monkeypatch):
    # Holding the first thread on its copy of `mantine_dark` leaves the cache with
    # `mantine_light` only, which is when the second thread arrives.
    dark = pio.templates["mantine_dark"]

    def slow_deepcopy(obj):
        if obj is dark:
            time.sleep(0.5)
        return copy.deepcopy(obj)

    monkeypatch.setattr(mt, "copy", types.SimpleNamespace(deepcopy=slow_deepcopy))

    errors: list[BaseException] = []

    def render():
        try:
            mt.apply_brand_theme()
        except BaseException as exc:  # noqa: BLE001 - surfaced by the assert below
            errors.append(exc)

    first = threading.Thread(target=render)
    second = threading.Thread(target=render)
    first.start()
    time.sleep(0.1)
    second.start()
    first.join()
    second.join()

    assert errors == []
    assert set(mt._vanilla) == set(mt._TEMPLATE_SCHEMES)
