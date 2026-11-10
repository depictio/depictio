"""Names and contents of browser uploads, checked before anything is stored."""

import pytest
from fastapi import HTTPException

from depictio.api.v1.endpoints.datacollections_endpoints.utils import (
    _phylogeny_format,
    _unique_image_names,
    _upload_basename,
    _validate_geojson_bytes,
)


@pytest.mark.parametrize(
    ("sent", "expected"),
    [
        ("table.csv", "table.csv"),
        # A dropped folder sends the path relative to it (the 500 this guards).
        ("demo_upload_files/table.csv", "table.csv"),
        ("a\\b\\table.csv", "table.csv"),
        ("/etc/passwd", "passwd"),
        ("../../secrets.env", "secrets.env"),
        ("run/..", "upload.dat"),
        ("", "upload.dat"),
        (None, "upload.dat"),
        ("bad\x00name.csv", "upload.dat"),
    ],
)
def test_upload_basename_is_one_safe_segment(sent, expected):
    assert _upload_basename(sent) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("(A:1,B:2);\n", "newick"),
        ("  ((A,B),C);", "newick"),
        ("#NEXUS\nbegin trees;", "nexus"),
        ("sample,value\n1,2\n", None),
        ("(no terminator", None),
    ],
)
def test_phylogeny_format_comes_from_the_content(text, expected):
    assert _phylogeny_format(text) == expected


def test_geojson_must_be_a_feature_collection():
    _validate_geojson_bytes(b'{"type": "FeatureCollection", "features": []}')
    for body in (b'{"type": "Feature"}', b"[1, 2]", b"not json"):
        with pytest.raises(HTTPException) as caught:
            _validate_geojson_bytes(body)
        assert caught.value.status_code == 400


def test_image_names_are_made_unique_and_checked():
    files = [(b"x", "a/slide.png"), (b"x", "b/slide.png"), (b"x", "c/SLIDE.png")]
    assert _unique_image_names(files, [".png"]) == ["slide.png", "slide_2.png", "SLIDE_3.png"]
    with pytest.raises(HTTPException):
        _unique_image_names([(b"x", "notes.txt")], [".png"])
