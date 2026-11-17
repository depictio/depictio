"""The viewer's nginx must let a project bundle through to the API (#1303).

A push lands on the instance's public URL, which is the viewer's: its nginx
proxies ``/depictio/api/`` to the backend. The server-wide
``client_max_body_size 200m`` would refuse any bundle above 200 MB with a 413,
whatever the ingress allows, and buffering the body would write a multi-GB
bundle to the viewer pod's disk before the API sees the first byte.
"""

from __future__ import annotations

import re
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[3].parent / "docker-images" / "nginx.conf.template"
BUNDLE_UPLOAD = "/depictio/api/v1/migrate/inbound/requests"


def _location_block(text: str, header: str) -> str:
    start = text.index(header)
    depth, i = 0, text.index("{", start)
    begin = i
    while True:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[begin : i + 1]
        i += 1


def test_bundle_upload_is_not_capped_or_buffered_by_the_viewer():
    text = TEMPLATE.read_text()
    block = _location_block(text, f"location = {BUNDLE_UPLOAD}")
    assert re.search(r"client_max_body_size\s+0\s*;", block), "the API enforces MAX_BUNDLE_BYTES"
    assert re.search(r"proxy_request_buffering\s+off\s*;", block)
    assert "proxy_pass http://$upstream" in block
    for directive in ("proxy_read_timeout", "proxy_send_timeout"):
        assert re.search(rf"{directive}\s+3600s\s*;", block), directive


def test_other_api_routes_keep_the_server_wide_cap():
    text = TEMPLATE.read_text()
    assert re.search(r"^\s*client_max_body_size\s+200m\s*;", text, re.M)
    assert "client_max_body_size" not in _location_block(text, "location /depictio/api/ ")
