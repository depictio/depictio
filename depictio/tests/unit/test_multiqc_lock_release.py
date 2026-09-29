"""MultiQC build locks are released when the worker running the task dies."""

from types import SimpleNamespace

import pytest

from depictio.api import celery_app


class FakeCache:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def delete(self, key):
        return self.store.pop(key, None) is not None


@pytest.fixture
def cache(monkeypatch):
    fake = FakeCache()
    monkeypatch.setattr("depictio.api.cache.get_cache", lambda: fake)
    return fake


def _fail(task_name, task_id, *args):
    celery_app._release_lock_of_lost_task(
        sender=SimpleNamespace(name=task_name), task_id=task_id, args=list(args)
    )


def test_lost_build_task_releases_its_lock(cache):
    cache.store["multiqc:prerender_build_lock:dc=dc1"] = "task-1"
    _fail("build_multiqc_prerender", "task-1", "dc1")
    assert "multiqc:prerender_build_lock:dc=dc1" not in cache.store


def test_lost_prewarm_task_releases_its_lock(cache):
    cache.store["multiqc:prewarm_lock:dashboard=d1"] = "task-2"
    _fail("prewarm_multiqc_dashboard", "task-2", "d1")
    assert cache.store == {}


def test_lock_held_by_another_task_is_kept(cache):
    cache.store["multiqc:prerender_build_lock:dc=dc1"] = "task-new"
    _fail("prewarm_multiqc_dc_all_plots", "task-old", "dc1")
    assert cache.store["multiqc:prerender_build_lock:dc=dc1"] == "task-new"


def test_other_tasks_are_ignored(cache):
    cache.store["multiqc:prerender_build_lock:dc=dc1"] = "task-1"
    _fail("depictio.figure.build_preview", "task-1", "dc1")
    assert "multiqc:prerender_build_lock:dc=dc1" in cache.store
