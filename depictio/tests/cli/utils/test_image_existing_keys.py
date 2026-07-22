"""Existing-key lookup for image pushes: one LIST instead of a HEAD per image.

Skipping already-uploaded images used to cost one ``head_object`` per file, so a
10k-image push paid 10k round-trips before uploading anything. A paginated LIST
answers the same question in ~1 request per 1000 keys. These tests pin the
pagination, the key set, and the deliberate fail-open behaviour.
"""

from depictio.cli.cli.commands.images import _list_existing_keys


class FakePaginator:
    """Mimics boto3's list_objects_v2 paginator over fixed pages."""

    def __init__(self, pages, calls):
        self._pages = pages
        self._calls = calls

    def paginate(self, **kwargs):
        self._calls.append(kwargs)
        yield from self._pages


class FakeS3:
    def __init__(self, pages=None, raises=False):
        self.pages = pages or []
        self.raises = raises
        self.paginate_calls: list[dict] = []
        self.head_calls = 0

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        if self.raises:
            raise RuntimeError("LIST not permitted")
        return FakePaginator(self.pages, self.paginate_calls)

    def head_object(self, **kwargs):  # pragma: no cover - must never be called
        self.head_calls += 1
        raise AssertionError("head_object must not be used to enumerate keys")


def test_collects_keys_across_pages():
    s3 = FakeS3(
        pages=[
            {"Contents": [{"Key": "img/a.png"}, {"Key": "img/b.png"}]},
            {"Contents": [{"Key": "img/c.png"}]},
        ]
    )
    assert _list_existing_keys(s3, "bucket", "img/") == {"img/a.png", "img/b.png", "img/c.png"}


def test_one_paginate_call_regardless_of_key_count():
    """The whole point: request count is driven by pages, not by image count."""
    pages = [{"Contents": [{"Key": f"img/{i}.png"} for i in range(1000)]} for _ in range(3)]
    s3 = FakeS3(pages=pages)
    keys = _list_existing_keys(s3, "bucket", "img/")
    assert len(keys) == 1000  # de-duplicated across pages by construction
    assert len(s3.paginate_calls) == 1
    assert s3.head_calls == 0


def test_passes_bucket_and_prefix():
    s3 = FakeS3(pages=[{"Contents": []}])
    _list_existing_keys(s3, "mybucket", "some/prefix/")
    assert s3.paginate_calls == [{"Bucket": "mybucket", "Prefix": "some/prefix/"}]


def test_empty_bucket_yields_empty_set():
    assert _list_existing_keys(FakeS3(pages=[{}]), "bucket", "img/") == set()


def test_list_failure_fails_open_to_empty_set():
    """On failure we re-upload rather than wrongly skip — the safe direction."""
    assert _list_existing_keys(FakeS3(raises=True), "bucket", "img/") == set()
