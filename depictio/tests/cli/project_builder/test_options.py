"""The project and collection options the builder writes, and the rules each keeps.

Wildcards, reader options, map coordinates, metatype, links and the data
management platform URL: each written as the shipped templates write it,
refused when the builder could not have produced it, and still a valid
``Project`` once resolved.
"""

from __future__ import annotations

import pytest

from depictio.cli.cli.utils.data_root import LocalDataRoot
from depictio.project_builder import plan, validate
from depictio.project_builder.assemble import (
    DcDraft,
    ImageProps,
    LinkDraft,
    MultiQCProps,
    ProjectDraft,
    ReaderOptions,
    TableProps,
    WildcardDraft,
    WorkflowDraft,
    build_template,
)
from depictio.project_builder.errors import BuilderRefused
from depictio.project_builder.match import match_collection
from depictio.project_builder.validate import validate_inline_template

from ._fixtures import project, scan_dc, table_dc


def _refusal(template, *, remote: bool = False) -> str:
    with pytest.raises(BuilderRefused) as exc:
        validate_inline_template(template, remote=remote)
    assert (exc.value.status, exc.value.code) == (422, "inline_template_invalid")
    return exc.value.detail


def _dc(template: dict, index: int = 0) -> dict:
    return template["workflows"][0]["data_collections"][index]


def _properties(template: dict, index: int = 0) -> dict:
    return _dc(template, index)["config"]["dc_specific_properties"]


def _regex_config(template: dict, index: int = 0) -> dict:
    return _dc(template, index)["config"]["scan"]["scan_parameters"]["regex_config"]


def _sample_scan(**fields) -> DcDraft:
    return scan_dc(
        "quant",
        regex=r"^star/{sample}/quant\.tsv$",
        wildcards=[WildcardDraft(name="sample", regex="[^/]+")],
        **fields,
    )


def _resolved(template: dict, root) -> dict:
    """The config a server would create the project from, checked as creation checks it."""
    config = plan.resolve_inline(template, root)[0]
    plan.check_project(config)
    return config


# ── wildcards ────────────────────────────────────────────────────────────────


class TestWildcards:
    def test_they_are_written_in_the_scan_s_own_shape(self):
        template = build_template(project(_sample_scan()))
        assert _regex_config(template) == {
            "pattern": r"^star/{sample}/quant\.tsv$",
            "wildcards": [{"name": "sample", "wildcard_regex": "[^/]+"}],
        }
        assert validate_inline_template(template, remote=False) == []

    def test_a_scan_without_them_has_no_wildcards_key(self):
        template = build_template(project(scan_dc()))
        assert "wildcards" not in _regex_config(template)

    def test_a_single_file_collection_carries_none(self):
        dc = table_dc(wildcards=[WildcardDraft(name="sample", regex="x")])
        template = build_template(project(dc))
        assert set(_dc(template)["config"]["scan"]["scan_parameters"]) == {"filename"}

    def test_they_match_and_resolve_like_any_scan(self, root):
        dc = _sample_scan()
        found = match_collection(root, "flat", None, dc)
        assert found["files"] == ["star/S1/quant.tsv", "star/S2/quant.tsv", "star/S3/quant.tsv"]
        config = _resolved(build_template(project(dc)), root)
        scan = config["workflows"][0]["data_collections"][0]["config"]["scan"]
        assert scan["scan_parameters"]["regex_config"]["wildcards"] == [
            {"name": "sample", "wildcard_regex": "[^/]+"}
        ]

    def test_each_value_becomes_the_column_it_names(self):
        from depictio.cli.cli.utils.scan_utils import wildcard_values

        template = build_template(project(_sample_scan()))
        regex_config = _regex_config(template)
        values = wildcard_values(
            regex_config["pattern"], regex_config["wildcards"], "/data/run/star/S2/quant.tsv"
        )
        assert values == {"sample": "S2"}

    @pytest.mark.parametrize(
        ("wildcards", "message"),
        [
            ([{"name": "1st", "wildcard_regex": "x"}], "must be a letter or _"),
            ([{"name": "sample-id", "wildcard_regex": "x"}], "must be a letter or _"),
            ([{"name": "SAMPLE", "wildcard_regex": "x"}], "reads as a template variable"),
            (
                [
                    {"name": "sample", "wildcard_regex": "x"},
                    {"name": "sample", "wildcard_regex": "y"},
                ],
                "declared twice",
            ),
            ([{"name": "run", "wildcard_regex": "x"}], "does not use the wildcard {run}"),
            ([{"name": "sample", "wildcard_regex": "("}], "invalid regex for the wildcard"),
            ([{"name": "sample", "wildcard_regex": "(?P<s>x)"}], "may not name groups"),
            ([{"name": "sample"}], "has a name and a wildcard_regex"),
            ("sample", "wildcards must be a list"),
        ],
    )
    def test_the_rules_they_keep(self, wildcards, message):
        template = build_template(project(_sample_scan()))
        _regex_config(template)["wildcards"] = wildcards
        if isinstance(wildcards, list) and wildcards and wildcards[0].get("name") == "run":
            _regex_config(template)["pattern"] = r"^star/x/quant\.tsv$"
        assert message in _refusal(template)

    def test_a_placeholder_no_wildcard_declares_is_refused(self):
        template = build_template(project(_sample_scan()))
        _regex_config(template)["pattern"] = r"^star/{sample}/{lane}\.tsv$"
        assert "{lane}, declared as no wildcard" in _refusal(template)

    def test_a_placeholder_without_any_wildcard_is_still_unknown(self):
        template = build_template(project(scan_dc(regex=r"^{sample}\.tsv$")))
        assert "declared as no wildcard" in _refusal(template)

    def test_a_regex_repetition_is_not_a_placeholder(self):
        template = build_template(project(scan_dc(regex=r"^S\d{2}\.tsv$")))
        assert validate_inline_template(template, remote=False) == []

    def test_the_regex_they_make_must_compile(self):
        dc = scan_dc(
            regex=r"^{sample}\.tsv$", wildcards=[WildcardDraft(name="sample", regex="[a-")]
        )
        assert "invalid regex" in _refusal(build_template(project(dc)))

    def test_they_survive_an_s3_root(self, s3_root):
        config = _resolved(build_template(project(_sample_scan()), remote=True), s3_root)
        scan = config["workflows"][0]["data_collections"][0]["config"]["scan"]
        # The remote scan keeps the regex with the wildcard spliced in.
        assert scan["mode"] == "s3_prefix"
        assert "([^/]+)" in scan["scan_parameters"]["pattern"]


# ── reader options ───────────────────────────────────────────────────────────


class TestReaderOptions:
    def _table(self, fmt: str = "csv", **reader) -> DcDraft:
        return DcDraft(
            tag="sheet",
            type="table",
            mode="single",
            path="samplesheet.csv",
            props=TableProps(format=fmt, separator=";", reader=ReaderOptions(**reader)),
        )

    def test_they_join_the_separator_in_polars_kwargs(self):
        dc = self._table(
            has_header=False,
            skip_rows=2,
            comment_prefix="#",
            null_values=["NA", ""],
            quote_char="'",
            decimal_comma=True,
        )
        template = build_template(project(dc))
        assert _properties(template)["polars_kwargs"] == {
            "separator": ";",
            "has_header": False,
            "skip_rows": 2,
            "comment_prefix": "#",
            "null_values": ["NA", ""],
            "quote_char": "'",
            "decimal_comma": True,
        }
        assert validate_inline_template(template, remote=False) == []

    def test_unset_options_are_not_written(self):
        template = build_template(project(self._table(null_values=[])))
        assert _properties(template)["polars_kwargs"] == {"separator": ";"}

    def test_a_binary_table_gets_none(self):
        template = build_template(project(self._table("parquet", skip_rows=1)))
        assert "polars_kwargs" not in _properties(template)

    def test_they_are_refused_on_a_format_that_is_not_text(self):
        template = build_template(project(self._table(skip_rows=1)))
        _properties(template)["format"] = "xlsx"
        assert "csv and tsv files only" in _refusal(template)

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"skip_rows": "2"}, "skip_rows has the wrong type"),
            ({"skip_rows": True}, "skip_rows has the wrong type"),
            ({"skip_rows": -1}, "can't be negative"),
            ({"has_header": "no"}, "has_header has the wrong type"),
            ({"separator": ";;"}, "the separator is one character"),
            ({"quote_char": "''"}, "one character"),
            ({"null_values": ["NA", 0]}, "a list of strings"),
            ({"infer_schema_length": 0}, "not infer_schema_length"),
            ({"try_parse_dates": True}, "not try_parse_dates"),
        ],
    )
    def test_the_rules_they_keep(self, kwargs, message):
        template = build_template(project(self._table()))
        _properties(template)["polars_kwargs"] = kwargs
        assert message in _refusal(template)

    def test_an_image_table_takes_them_too(self):
        dc = DcDraft(
            tag="imgs",
            type="image",
            mode="single",
            path="images.csv",
            props=ImageProps(image_column="img", reader=ReaderOptions(comment_prefix="#")),
        )
        assert _properties(build_template(project(dc)))["polars_kwargs"] == {"comment_prefix": "#"}

    def test_the_reader_reads_what_they_say(self, tmp_path):
        import polars as pl

        from depictio.cli.cli.utils.deltatables import _lazy_scan_path

        path = tmp_path / "with_notes.csv"
        path.write_text("# exported 2026-10-01\nsample;value\nS1;1,5\nS2;NA\n")
        template = build_template(
            project(self._table(comment_prefix="#", null_values=["NA"], decimal_comma=True))
        )
        frame = _lazy_scan_path(str(path), "csv", _properties(template)["polars_kwargs"]).collect()
        assert frame.columns == ["sample", "value"]
        assert frame["value"].to_list() == [1.5, None]
        assert frame["value"].dtype == pl.Float64


# ── map coordinates ──────────────────────────────────────────────────────────


class TestCoordinates:
    def _table(self, **props) -> DcDraft:
        return DcDraft(
            tag="sites",
            type="table",
            mode="single",
            path="samplesheet.csv",
            props=TableProps(format="csv", **props),
        )

    def test_both_columns_and_the_crs_are_written(self, root):
        template = build_template(
            project(self._table(lat_column="lat", lon_column="lon", crs="EPSG:3857"))
        )
        properties = _properties(template)
        assert (properties["lat_column"], properties["lon_column"], properties["crs"]) == (
            "lat",
            "lon",
            "EPSG:3857",
        )
        assert validate_inline_template(template, remote=False) == []
        config = _resolved(template, root)
        written = config["workflows"][0]["data_collections"][0]["config"]
        assert written["dc_specific_properties"]["lat_column"] == "lat"

    def test_one_column_alone_is_refused(self):
        template = build_template(project(self._table(lat_column="lat")))
        assert "both a latitude and a longitude" in _refusal(template)

    def test_a_crs_alone_is_refused(self):
        template = build_template(project(self._table()))
        _properties(template)["crs"] = "EPSG:4326"
        assert "both a latitude and a longitude" in _refusal(template)

    def test_the_two_columns_must_differ(self):
        template = build_template(project(self._table(lat_column="xy", lon_column="xy")))
        assert "must differ" in _refusal(template)


# ── metatype ─────────────────────────────────────────────────────────────────


class TestMetatype:
    def test_automatic_follows_the_scan(self):
        template = build_template(project(table_dc(), scan_dc()))
        assert [_dc(template, i)["config"]["metatype"] for i in (0, 1)] == [
            "Metadata",
            "Aggregate",
        ]

    def test_an_override_wins(self):
        template = build_template(project(table_dc(metatype="Aggregate")))
        assert _dc(template)["config"]["metatype"] == "Aggregate"
        assert validate_inline_template(template, remote=False) == []

    def test_an_image_collection_has_one_only_when_set(self):
        def image(**fields):
            return DcDraft(
                tag="imgs",
                type="image",
                mode="single",
                path="images.csv",
                props=ImageProps(image_column="img"),
                **fields,
            )

        assert "metatype" not in _dc(build_template(project(image())))["config"]
        assert _dc(build_template(project(image(metatype="Metadata"))))["config"]["metatype"] == (
            "Metadata"
        )

    @pytest.mark.parametrize("metatype", ["Joined", "metadata", 3])
    def test_other_values_are_refused(self, metatype):
        template = build_template(project(table_dc()))
        _dc(template)["config"]["metatype"] = metatype
        assert "metatype must be Aggregate or Metadata" in _refusal(template)


# ── links ────────────────────────────────────────────────────────────────────


def _linked(*links: LinkDraft) -> ProjectDraft:
    return ProjectDraft(
        name="Linked",
        workflows=[
            WorkflowDraft(
                name="main",
                data_collections=[
                    table_dc("sheet"),
                    _sample_scan(),
                    DcDraft(
                        tag="mqc",
                        type="multiqc",
                        mode="single",
                        path="multiqc/multiqc_data/multiqc.parquet",
                        props=MultiQCProps(),
                    ),
                ],
            )
        ],
        links=list(links),
    )


class TestLinks:
    def test_the_target_type_and_defaults_come_from_the_target(self):
        template = build_template(
            _linked(
                LinkDraft(
                    source_tag="sheet",
                    source_column="sample",
                    target_tag="quant",
                    target_field="sample",
                ),
                LinkDraft(source_tag="sheet", source_column="sample", target_tag="mqc"),
            )
        )
        assert template["links"] == [
            {
                "source_dc_tag": "sheet",
                "source_column": "sample",
                "target_dc_tag": "quant",
                "target_type": "table",
                "link_config": {"resolver": "direct", "target_field": "sample"},
            },
            {
                "source_dc_tag": "sheet",
                "source_column": "sample",
                "target_dc_tag": "mqc",
                "target_type": "multiqc",
                "link_config": {"resolver": "sample_mapping", "target_field": "sample_name"},
            },
        ]
        assert validate_inline_template(template, remote=False) == []

    def test_a_pattern_link_keeps_its_pattern(self):
        template = build_template(
            _linked(
                LinkDraft(
                    source_tag="sheet",
                    source_column="sample",
                    target_tag="quant",
                    resolver="pattern",
                    pattern="{sample}_R1",
                    description="reads of the sample",
                )
            )
        )
        link = template["links"][0]
        assert link["link_config"] == {"resolver": "pattern", "pattern": "{sample}_R1"}
        assert link["description"] == "reads of the sample"
        assert validate_inline_template(template, remote=False) == []

    def test_no_links_writes_no_key(self):
        assert "links" not in build_template(_linked())

    def test_a_created_project_keeps_them_by_tag(self, root):
        template = build_template(
            _linked(LinkDraft(source_tag="sheet", source_column="sample", target_tag="mqc"))
        )
        config = _resolved(template, root)
        assert config["links"][0]["source_dc_tag"] == "sheet"
        assert config["links"][0]["target_dc_tag"] == "mqc"

    @pytest.mark.parametrize(
        ("change", "message"),
        [
            ({"source_dc_tag": "ghost"}, "'ghost' is not a data collection"),
            ({"target_dc_tag": "ghost"}, "'ghost' is not a data collection"),
            ({"target_dc_tag": "sheet"}, "can't filter itself"),
            ({"target_type": "multiqc"}, "target_type must be 'table'"),
            ({"link_config": {"resolver": "region"}}, "unknown resolver 'region'"),
            ({"link_config": {"resolver": "pattern"}}, "needs a pattern with {sample}"),
            (
                {"link_config": {"resolver": "pattern", "pattern": "x"}},
                "needs a pattern with {sample}",
            ),
            (
                {"link_config": {"resolver": "direct", "pattern": "{sample}"}},
                "for the pattern resolver",
            ),
            ({"link_config": {"mappings": {}}}, "takes a resolver, target_field and pattern only"),
            ({"source_dc_id": "abc"}, "unexpected keys"),
            ({"source_column": " "}, "Source column cannot be empty"),
        ],
    )
    def test_the_rules_they_keep(self, change, message):
        template = build_template(
            _linked(LinkDraft(source_tag="sheet", source_column="sample", target_tag="quant"))
        )
        template["links"][0].update(change)
        assert message in _refusal(template)

    def test_a_multiqc_collection_is_no_source(self):
        template = build_template(
            _linked(LinkDraft(source_tag="mqc", source_column="sample", target_tag="sheet"))
        )
        assert "has no rows to filter from" in _refusal(template)

    def test_a_target_this_depictio_cannot_filter_is_refused(self):
        tree = DcDraft(
            tag="tree",
            type="phylogeny",
            mode="single",
            path="trees/tree.nwk",
            props={"kind": "phylogeny"},
        )
        draft = _linked(LinkDraft(source_tag="sheet", source_column="sample", target_tag="tree"))
        draft.workflows[0].data_collections.append(tree)
        assert "can't filter a phylogeny collection" in _refusal(build_template(draft))

    def test_links_must_be_a_list(self):
        template = build_template(_linked())
        template["links"] = {"source_dc_tag": "sheet"}
        assert "links must be a list" in _refusal(template)


# ── project-level fields ─────────────────────────────────────────────────────


class TestProjectFields:
    def test_the_data_management_platform_url_is_written_and_kept(self, root):
        draft = project(table_dc())
        draft.data_management_platform_project_url = "https://lims.example.org/projects/42"
        template = build_template(draft)
        assert template["data_management_platform_project_url"] == (
            "https://lims.example.org/projects/42"
        )
        config = _resolved(template, root)
        assert config["data_management_platform_project_url"].endswith("/projects/42")

    @pytest.mark.parametrize("url", ["lims.example.org/p", "ftp://x", "https://x y"])
    def test_it_must_be_an_http_url(self, url):
        template = build_template(project(table_dc()))
        template["data_management_platform_project_url"] = url
        assert "must be an http(s) URL" in _refusal(template)

    def test_realtime_is_the_project_flag(self, root):
        draft = project(table_dc())
        draft.realtime = True
        config = _resolved(build_template(draft), root)
        assert config["realtime"] == {"enabled": True, "debounce_ms": 1000}


def test_every_option_at_once_is_one_valid_template(root):
    draft = _linked(LinkDraft(source_tag="sheet", source_column="sample", target_tag="quant"))
    draft.realtime = True
    draft.data_management_platform_project_url = "https://lims.example.org/p/1"
    draft.workflows[0].data_collections[0] = table_dc(metatype="Metadata")
    template = build_template(draft)
    assert validate_inline_template(template, remote=False) == []
    assert validate.TOP_LEVEL_KEYS >= set(template)
    _resolved(template, LocalDataRoot(root.location))
