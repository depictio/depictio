"""``add_filter`` for the TextInput interactive filter (regex match on a string column)."""

import polars as pl
import pytest

from depictio.api.v1.deltatables_utils import (
    _generate_filter_hash,
    add_filter,
    clean_filter_payload,
    is_valid_text_pattern,
    process_metadata_and_filter,
)

GUIDES = ["ACGGG", "AAAAAT", "acgtt", None, "A+C", "TTGGGA"]


def _apply(value, **options) -> list | str:
    """The rows of GUIDES a TextInput on `guide` keeps, or "unfiltered" when it adds nothing."""
    filters: list = []
    add_filter(filters, "TextInput", "guide", value, **options)
    if not filters:
        return "unfiltered"
    frame = pl.DataFrame({"guide": GUIDES})
    return frame.filter(pl.all_horizontal(filters))["guide"].to_list()


class TestMatching:
    def test_substring(self):
        assert _apply("GGG") == ["ACGGG", "TTGGGA"]

    def test_end_anchor(self):
        assert _apply("GGG$") == ["ACGGG"]

    def test_start_anchor(self):
        assert _apply("^ACG") == ["ACGGG", "acgtt"]

    def test_repetition(self):
        assert _apply("A{5,}") == ["AAAAAT"]

    def test_case_insensitive_by_default(self):
        assert _apply("acg") == ["ACGGG", "acgtt"]

    def test_case_sensitive(self):
        assert _apply("acg", case_sensitive=True) == ["acgtt"]
        assert _apply("ACG", case_sensitive=True) == ["ACGGG"]

    def test_surrounding_whitespace_is_trimmed(self):
        assert _apply("  GGG$ ") == ["ACGGG"]

    def test_nulls_never_match(self):
        kept = _apply(".*")
        assert None not in kept
        assert len(kept) == len(GUIDES) - 1

    def test_a_non_string_column_is_matched_on_its_text(self):
        filters: list = []
        add_filter(filters, "TextInput", "n", "^1", dtype=pl.Int64)
        frame = pl.DataFrame({"n": [1, 12, 21, 3]})
        assert frame.filter(pl.all_horizontal(filters))["n"].to_list() == [1, 12]


class TestLiteralMode:
    def test_metacharacters_match_literally(self):
        assert _apply("A+", match_mode="contains") == ["A+C"]

    def test_the_same_text_as_a_regex_is_a_pattern(self):
        assert "A+C" in _apply("A+")
        assert "AAAAAT" in _apply("A+")

    def test_literal_is_case_insensitive_by_default(self):
        assert _apply("a+c", match_mode="contains") == ["A+C"]

    def test_literal_case_sensitive(self):
        assert _apply("a+c", match_mode="contains", case_sensitive=True) == []

    def test_unknown_mode_falls_back_to_regex(self):
        assert _apply("GGG$", match_mode="glob") == ["ACGGG"]


class TestNoFilter:
    @pytest.mark.parametrize("value", ["", "   ", "\t", None])
    def test_empty_or_blank_value_adds_no_filter(self, value):
        assert _apply(value) == "unfiltered"

    @pytest.mark.parametrize("value", ["(", "[A-", "a{1000}{1000}", "(?=x)"])
    def test_invalid_regex_returns_the_frame_unfiltered(self, value):
        assert _apply(value) == "unfiltered"

    def test_invalid_regex_is_fine_as_literal_text(self):
        assert _apply("(", match_mode="contains") == []

    def test_a_list_value_adds_no_filter(self):
        assert _apply(["GGG"]) == "unfiltered"


class TestPatternCheck:
    def test_regex_validity(self):
        assert is_valid_text_pattern("GGG$")
        assert not is_valid_text_pattern("(")

    def test_literal_text_is_always_valid(self):
        assert is_valid_text_pattern("(", "contains")


class TestPayloadPlumbing:
    def test_options_travel_through_clean_filter_payload(self):
        cleaned = clean_filter_payload(
            [
                {
                    "index": "a",
                    "value": "GGG$",
                    "metadata": {
                        "column_name": "guide",
                        "interactive_component_type": "TextInput",
                        "case_sensitive": True,
                        "match_mode": "contains",
                    },
                }
            ]
        )
        assert cleaned == [
            {
                "interactive_component_type": "TextInput",
                "column_name": "guide",
                "value": "GGG$",
                "case_sensitive": True,
                "match_mode": "contains",
            }
        ]

    def test_options_are_read_by_process_metadata_and_filter(self):
        frame = pl.DataFrame({"guide": GUIDES})
        for options, expected in (
            ({}, ["ACGGG", "acgtt"]),
            ({"case_sensitive": True}, ["acgtt"]),
        ):
            filters = process_metadata_and_filter(
                [
                    {
                        "interactive_component_type": "TextInput",
                        "column_name": "guide",
                        "value": "^acg",
                        **options,
                    }
                ]
            )
            kept = frame.filter(pl.all_horizontal(filters))["guide"].to_list()
            assert kept == expected

    def test_options_are_part_of_the_cache_hash(self):
        base = {"interactive_component_type": "TextInput", "column_name": "guide", "value": "acg"}
        insensitive = _generate_filter_hash([base])
        assert insensitive == _generate_filter_hash([{**base, "case_sensitive": False}])
        assert insensitive != _generate_filter_hash([{**base, "case_sensitive": True}])
        assert insensitive != _generate_filter_hash([{**base, "match_mode": "contains"}])
        assert insensitive != _generate_filter_hash([{**base, "value": "acgt"}])


class TestLinkPropagation:
    """A TextInput reaches a linked collection as a pattern resolved on its own one."""

    @staticmethod
    def _source(value, **meta) -> dict:
        return {
            "index": "guide-text",
            "value": value,
            "metadata": {
                "dc_id": "dc1",
                "column_name": "guide",
                "interactive_component_type": "TextInput",
                **meta,
            },
        }

    def test_a_usable_pattern_becomes_a_text_match(self):
        from depictio.api.v1.filter_links import _text_match_spec

        assert _text_match_spec(self._source("GGG$")) == {
            "case_sensitive": False,
            "match_mode": "regex",
        }
        assert _text_match_spec(self._source("A+", case_sensitive=True, match_mode="contains")) == {
            "case_sensitive": True,
            "match_mode": "contains",
        }

    @pytest.mark.parametrize("value", ["", "  ", "(", None, ["GGG"]])
    def test_an_unusable_pattern_resolves_to_nothing(self, value):
        from depictio.api.v1.filter_links import _is_text_filter, _text_match_spec

        source = self._source(value)
        assert _is_text_filter(source)
        assert _text_match_spec(source) is None

    def test_other_filters_are_not_text_matches(self):
        from depictio.api.v1.filter_links import _is_text_filter, _text_match_spec

        other = self._source(["a"], interactive_component_type="MultiSelect")
        assert not _is_text_filter(other)
        assert _text_match_spec(other) is None

    def test_the_resolution_request_accepts_the_spec(self):
        from depictio.models.models.links import LinkResolutionRequest

        request = LinkResolutionRequest(
            source_dc_id="a",
            source_column="guide",
            filter_values=["GGG$"],
            target_dc_id="b",
            text_match={"case_sensitive": False, "match_mode": "regex"},
        )
        assert request.text_match is not None and request.text_match.match_mode == "regex"


@pytest.mark.asyncio
class TestLinkTranslation:
    """`_translate_filter_values` with a text match, on an in-memory source collection."""

    @staticmethod
    def _patch(monkeypatch):
        from depictio.api.v1.endpoints.links_endpoints import routes

        frame = pl.DataFrame(
            {
                "sample": ["s1", "s2", "s3", "s4"],
                "guide": ["ACGGG", "TTTTT", "acggg", None],
            }
        ).lazy()
        monkeypatch.setattr(
            routes.deltatables_collection,
            "find_one",
            lambda *_a, **_k: {"delta_table_location": "memory://x"},
        )
        monkeypatch.setattr(pl, "scan_delta", lambda *_a, **_k: frame)
        return routes

    async def test_matching_rows_give_their_join_values(self, monkeypatch):
        from depictio.models.models.links import TextMatchSpec

        routes = self._patch(monkeypatch)
        values = await routes._translate_filter_values(
            "dc1", "guide", ["GGG$"], "sample", text_match=TextMatchSpec()
        )
        assert sorted(values) == ["s1", "s3"]

    async def test_case_sensitive_match(self, monkeypatch):
        from depictio.models.models.links import TextMatchSpec

        routes = self._patch(monkeypatch)
        values = await routes._translate_filter_values(
            "dc1", "guide", ["GGG$"], "sample", text_match=TextMatchSpec(case_sensitive=True)
        )
        assert values == ["s1"]

    async def test_nothing_matching_gives_no_join_values(self, monkeypatch):
        from depictio.models.models.links import TextMatchSpec

        routes = self._patch(monkeypatch)
        values = await routes._translate_filter_values(
            "dc1", "guide", ["CCCCC"], "sample", text_match=TextMatchSpec()
        )
        assert values == []


class TestPatternLength:
    def test_a_pattern_over_the_cap_filters_nothing_and_is_flagged(self):
        from depictio.api.v1.deltatables_utils import MAX_TEXT_PATTERN_LENGTH

        too_long = "A" * (MAX_TEXT_PATTERN_LENGTH + 1)
        assert _apply(too_long) == "unfiltered"
        assert is_valid_text_pattern(too_long) is False
        assert is_valid_text_pattern(too_long, "contains") is False

    def test_a_pattern_at_the_cap_still_filters(self):
        from depictio.api.v1.deltatables_utils import MAX_TEXT_PATTERN_LENGTH

        assert _apply("A" * MAX_TEXT_PATTERN_LENGTH) == []
