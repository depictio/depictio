"""``embed_allowed_origins`` entries must be single CSP source expressions.

The list is joined with spaces into ``frame-ancestors`` by
``services/export/embed.py::build_embed_csp``. Anything in an entry that CSP
treats as a separator therefore escapes the directive it was meant to sit in:
``https://a; script-src *`` closes ``frame-ancestors`` and opens a second
directive, rewriting the policy of every embed the instance serves. Only a bare
``*`` was rejected before, which is the least interesting of the bad values.

These are settings-level tests on purpose: rejecting at startup means a bad
value stops the process that reads it, rather than silently widening a security
header on every response.
"""

from __future__ import annotations

import pytest

from depictio.api.v1.configs.settings_models import FastAPIConfig


class TestAcceptedOrigins:
    @pytest.mark.parametrize(
        "origin",
        [
            "https://lab.example.org",
            "http://localhost:8899",
            # A host wildcard is a legitimate CSP source, unlike a bare '*'.
            "https://*.example.org",
            "https://a.b-c.de:65535",
        ],
    )
    def test_valid_origins_are_kept(self, origin: str) -> None:
        assert FastAPIConfig(embed_allowed_origins=[origin]).embed_allowed_origins == [origin]

    def test_comma_separated_string_is_split(self) -> None:
        cfg = FastAPIConfig(embed_allowed_origins="https://a.example.org, https://b.example.org")
        assert cfg.embed_allowed_origins == ["https://a.example.org", "https://b.example.org"]

    def test_empty_is_allowed(self) -> None:
        """Empty means frame-ancestors 'none' — the default, and not an error."""
        assert FastAPIConfig(embed_allowed_origins=[]).embed_allowed_origins == []


class TestRejectedOrigins:
    @pytest.mark.parametrize(
        "origin,why",
        [
            ("https://a; script-src *", "injects a second CSP directive"),
            ("https://a https://b", "whitespace splits one entry into two sources"),
            # build_embed_csp runs str.format over the assembled policy, so a
            # brace raises at request time rather than at startup.
            ("https://a{script_src}", "breaks the CSP template"),
            ("javascript:alert(1)", "not an http(s) origin"),
            ("//example.org", "no scheme"),
            ("https://a.example.org/embed", "a path is not part of an origin"),
        ],
    )
    def test_malformed_origin_is_refused(self, origin: str, why: str) -> None:
        with pytest.raises(ValueError, match="not a valid"):
            FastAPIConfig(embed_allowed_origins=[origin])

    def test_bare_wildcard_still_refused(self) -> None:
        """Pre-existing guard; kept so tightening the regex cannot lose it."""
        with pytest.raises(ValueError, match=r"contains '\*'"):
            FastAPIConfig(embed_allowed_origins=["*"])

    def test_one_bad_entry_rejects_the_whole_list(self) -> None:
        with pytest.raises(ValueError):
            FastAPIConfig(
                embed_allowed_origins=["https://good.example.org", "https://bad; script-src *"]
            )
