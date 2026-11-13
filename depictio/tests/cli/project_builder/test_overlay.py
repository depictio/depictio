"""A shipped template edited in the Project Builder (``project_builder.overlay``).

The template is never rewritten: the server re-reads it and applies the
reader's edits. Every shipped template is held to the same promises:

- no edit is the template as it ships, byte for byte, and resolves exactly as
  ``resolve_template`` resolves it;
- adding a collection keeps every collection and link of the template;
- removing a collection takes out what is built from it, and nothing else;
- repointing a file changes that file, and no conditional rule undoes it.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from depictio.cli.cli.utils.templates import (
    _load_yaml,
    _projects_roots,
    resolve_template,
    resolve_template_config,
)
from depictio.project_builder import overlay
from depictio.project_builder.assemble import (
    DcDraft,
    LinkDraft,
    ProjectDraft,
    TableProps,
    WorkflowDraft,
    build_template,
)
from depictio.project_builder.errors import BuilderRefused
from depictio.project_builder.overlay import ScanEdit, SourceEdit, TemplateEdits, WorkflowEdit

AMPLISEQ = "nf-core/ampliseq/2.18.0"


def _shipped() -> list[tuple[str, Path]]:
    found: dict[str, Path] = {}
    for root in _projects_roots():
        for path in sorted(Path(root).rglob("template.yaml")):
            raw = _load_yaml(str(path))
            template_id = (raw.get("template") or {}).get("template_id")
            if template_id and template_id not in found:
                found[str(template_id)] = path
    return sorted(found.items())


SHIPPED = _shipped()
IDS = [template_id for template_id, _ in SHIPPED]


def _tags(raw: dict) -> list[str]:
    return [
        dc["data_collection_tag"]
        for workflow in raw.get("workflows") or []
        for dc in workflow.get("data_collections") or []
    ]


def _links(raw: dict) -> list[tuple[str, str]]:
    return [(link["source_dc_tag"], link["target_dc_tag"]) for link in raw.get("links") or []]


def _extra(tag: str = "builder_extra", workflow: str = "added") -> dict:
    """The inline template of one extra table, as ``POST /builder/template`` builds it."""
    draft = ProjectDraft(
        name="Edited",
        workflows=[
            WorkflowDraft(
                name=workflow,
                data_collections=[
                    DcDraft(
                        tag=tag,
                        type="table",
                        mode="single",
                        path="extra/sheet.csv",
                        props=TableProps(format="csv", separator=","),
                    )
                ],
            )
        ],
    )
    return build_template(draft)


def test_every_shipped_template_is_covered():
    assert len(SHIPPED) >= 50


@pytest.mark.parametrize("template_id", IDS)
def test_no_edit_is_the_template_as_it_ships(template_id):
    path = dict(SHIPPED)[template_id]
    raw, located, removed, warnings = overlay.compose(template_id, TemplateEdits(), remote=False)

    assert raw == _load_yaml(str(path))
    assert located == path.resolve()
    assert (removed, warnings) == ({}, [])


def _resolved(config: dict) -> dict:
    out = copy.deepcopy(config)
    out["template_origin"].pop("applied_at", None)
    return out


@pytest.mark.parametrize("template_id", IDS)
def test_no_edit_resolves_as_the_shipped_template_does(template_id, tmp_path, monkeypatch):
    monkeypatch.setenv("DEPICTIO_CONTEXT", "cli")
    raw, path, _removed, _warnings = overlay.compose(template_id, TemplateEdits(), remote=False)
    edited = resolve_template_config(
        raw, template_dir=path.parent, data_root=tmp_path, allow_missing_vars=True
    )
    shipped = resolve_template(template_id, tmp_path, allow_missing_vars=True)

    assert _resolved(edited[0]) == _resolved(shipped[0])
    assert edited[3] == shipped[3]  # the same dashboards
    assert edited[4] == shipped[4]  # the same variables


@pytest.mark.parametrize("template_id", IDS)
def test_adding_a_collection_keeps_every_collection_and_link(template_id):
    original = _load_yaml(str(dict(SHIPPED)[template_id]))
    raw, _path, removed, _warnings = overlay.compose(
        template_id, TemplateEdits(additions=_extra()), remote=False
    )

    assert _tags(raw) == [*_tags(original), "builder_extra"]
    assert _links(raw) == _links(original)
    assert raw["template"] == original["template"]
    assert removed == {}


@pytest.mark.parametrize("template_id", IDS)
def test_a_collection_added_to_a_template_workflow_joins_it(template_id):
    original = _load_yaml(str(dict(SHIPPED)[template_id]))
    first = original["workflows"][0]
    raw, *_ = overlay.compose(
        template_id, TemplateEdits(additions=_extra(workflow=first["name"])), remote=False
    )

    assert len(raw["workflows"]) == len(original["workflows"])
    tags = [dc["data_collection_tag"] for dc in raw["workflows"][0]["data_collections"]]
    assert tags == [dc["data_collection_tag"] for dc in first["data_collections"]] + [
        "builder_extra"
    ]
    # The workflow's own settings are the template's.
    assert {k: v for k, v in raw["workflows"][0].items() if k != "data_collections"} == {
        k: v for k, v in first.items() if k != "data_collections"
    }


@pytest.mark.parametrize("template_id", IDS)
def test_removing_a_collection_takes_out_only_what_is_built_from_it(template_id):
    original = _load_yaml(str(dict(SHIPPED)[template_id]))
    target = _tags(original)[0]
    edits = TemplateEdits(remove=[target], additions=_extra())
    raw, _path, removed, _warnings = overlay.compose(template_id, edits, remote=False)

    assert target in removed
    kept = _tags(raw)
    assert set(kept) == (set(_tags(original)) - set(removed)) | {"builder_extra"}
    assert not set(kept) & set(removed)
    # Nothing left names a removed collection, and every surviving link stays.
    assert all(source not in removed and target not in removed for source, target in _links(raw))
    assert _links(raw) == [
        (s, t) for s, t in _links(original) if s not in removed and t not in removed
    ]
    # Each collection left has what it is built from.
    described = overlay.describe_template(template_id)
    needs = {c["tag"]: c["needs"] for w in described["workflows"] for c in w["collections"]}
    for tag in kept:
        assert not set(needs.get(tag, [])) & set(removed), tag


@pytest.mark.parametrize("template_id", IDS)
def test_repointing_a_file_changes_that_file_only(template_id):
    described = overlay.describe_template(template_id)
    files = [c for w in described["workflows"] for c in w["collections"] if c["edit"] == "path"]
    if not files:
        pytest.skip("no collection read from one file it names itself")
    tag = files[0]["tag"]
    raw, *_ = overlay.compose(
        template_id, TemplateEdits(scans={tag: ScanEdit(path="moved/elsewhere.tsv")}), remote=False
    )
    original = _load_yaml(str(dict(SHIPPED)[template_id]))

    def location(config: dict, wanted: str):
        for workflow in config["workflows"]:
            for dc in workflow["data_collections"]:
                if dc["data_collection_tag"] == wanted:
                    scan = dc["config"].get("scan") or {}
                    return (scan.get("scan_parameters") or {}).get("filename")

    assert location(raw, tag) == "{DATA_ROOT}/moved/elsewhere.tsv"
    for other in _tags(original):
        if other != tag:
            assert location(raw, other) == location(original, other)
    for rule in raw["template"].get("conditional") or []:
        for override in rule.get("override_dcs") or []:
            if override.get("data_collection_tag") == tag:
                assert "scan_filename" not in override


# ── ampliseq, case by case ──────────────────────────────────────────────────


def test_ampliseq_is_described_whole():
    described = overlay.describe_template(AMPLISEQ)
    collections = [c for w in described["workflows"] for c in w["collections"]]

    assert len(collections) == 26
    assert sum(c["kind"] == "recipe" for c in collections) == 22
    assert described["dashboards"] == ["dashboards/base.yaml"]
    assert len(described["links"]) == 23
    assert "SAMPLESHEET_FILE" in {v["name"] for v in described["variables"]}
    sheet = next(c for c in collections if c["tag"] == "samplesheet")
    # Read through a variable: set the variable, the path is not edited.
    assert (sheet["kind"], sheet["edit"], sheet["variables"]) == (
        "file",
        None,
        ["SAMPLESHEET_FILE"],
    )
    ma = next(c for c in collections if c["tag"] == "ma_canonical")
    assert ma["needs"] == ["ancombc_results", "taxonomy_composition"]
    labelled = next(s for s in ma["sources"] if s["ref"] == "labelled_barplots")
    assert labelled["editable"] and labelled["glob_pattern"]


def test_a_removal_takes_its_dependants_with_it_and_says_why():
    _raw, _path, removed, _ = overlay.compose(
        AMPLISEQ, TemplateEdits(remove=["taxonomy_composition"]), remote=False
    )
    assert removed == {
        "taxonomy_composition": "removed in the Project Builder",
        "ma_canonical": "built from taxonomy_composition, removed in the Project Builder",
    }


def test_a_recipe_input_is_repointed_and_the_conditional_leaves_it():
    edits = TemplateEdits(
        sources={"taxonomy_composition": {"barplot_csv": SourceEdit(path="mine/level-4.csv")}}
    )
    raw, *_ = overlay.compose(AMPLISEQ, edits, remote=False)
    dc = next(
        dc
        for dc in raw["workflows"][0]["data_collections"]
        if dc["data_collection_tag"] == "taxonomy_composition"
    )
    assert dc["config"]["transform"]["source_overrides"]["barplot_csv"] == {
        "path": "mine/level-4.csv"
    }
    for rule in raw["template"]["conditional"]:
        for override in rule.get("override_dcs") or []:
            if override.get("data_collection_tag") == "taxonomy_composition":
                assert "barplot_csv" not in (override.get("source_overrides") or {})


def test_a_link_to_a_template_collection_takes_its_type():
    draft = ProjectDraft(
        name="Edited",
        workflows=[
            WorkflowDraft(
                name="added",
                data_collections=[
                    DcDraft(
                        tag="extra",
                        type="table",
                        mode="single",
                        path="extra/sheet.csv",
                        props=TableProps(format="csv", separator=","),
                    )
                ],
            )
        ],
        links=[LinkDraft(source_tag="extra", source_column="sample", target_tag="multiqc_data")],
    )
    additions = build_template(draft, link_targets=overlay.link_targets(AMPLISEQ))
    raw, *_ = overlay.compose(AMPLISEQ, TemplateEdits(additions=additions), remote=False)
    link = raw["links"][-1]
    assert (link["source_dc_tag"], link["target_dc_tag"], link["target_type"]) == (
        "extra",
        "multiqc_data",
        "multiqc",
    )
    assert link["link_config"] == {"resolver": "sample_mapping", "target_field": "sample_name"}


@pytest.mark.parametrize(
    ("edits", "says"),
    [
        (TemplateEdits(remove=["nope"]), "nope: not a data collection"),
        (TemplateEdits(scans={"nope": ScanEdit(path="a.tsv")}), "nope: not a data collection"),
        (
            TemplateEdits(scans={"phylogenetic_tree_canonical": ScanEdit(path="../out.nwk")}),
            "may not contain '..'",
        ),
        (
            TemplateEdits(scans={"phylogenetic_tree_canonical": ScanEdit(path="/etc/passwd")}),
            "relative to the data root",
        ),
        (
            TemplateEdits(scans={"phylogenetic_tree_canonical": ScanEdit(path="{NOPE}/t.nwk")}),
            "not a variable of this template",
        ),
        (TemplateEdits(scans={"samplesheet": ScanEdit(path="x.csv")}), "set the variable"),
        (TemplateEdits(scans={"multiqc_data": ScanEdit(path="x.parquet")}), "not read from one"),
        (TemplateEdits(scans={"multiqc_data": ScanEdit(regex="(")}), "invalid regex"),
        (
            TemplateEdits(sources={"samplesheet": {"x": SourceEdit(path="a.csv")}}),
            "not built by a recipe",
        ),
        (
            TemplateEdits(sources={"ma_canonical": {"nope": SourceEdit(path="a.csv")}}),
            "no input named 'nope'",
        ),
        (
            TemplateEdits(sources={"ma_canonical": {"ancombc": SourceEdit(path="a.csv")}}),
            "is another collection",
        ),
        (TemplateEdits(additions=_extra(tag="multiqc_data")), "already a collection"),
        (
            TemplateEdits(workflows={"nope": WorkflowEdit(repository_url="https://x.org/r")}),
            "nope: not a workflow of this template",
        ),
        (
            TemplateEdits(workflows={"ampliseq": WorkflowEdit(repository_url="ftp://x.org/r")}),
            "an http(s) URL",
        ),
    ],
)
def test_an_edit_that_does_not_fit_is_refused_with_why(edits, says):
    with pytest.raises(BuilderRefused) as refused:
        overlay.compose(AMPLISEQ, edits, remote=False)
    assert refused.value.status == 422
    assert refused.value.code == overlay.EDITS_INVALID
    assert says in refused.value.detail


def test_removing_every_collection_is_refused():
    every = [
        c["tag"] for w in overlay.describe_template(AMPLISEQ)["workflows"] for c in w["collections"]
    ]
    with pytest.raises(BuilderRefused, match="Every data collection was removed"):
        overlay.compose(AMPLISEQ, TemplateEdits(remove=every), remote=False)


def test_a_scan_pattern_must_keep_its_wildcards():
    with_wildcards = [
        (template_id, c["tag"], c["wildcards"])
        for template_id in IDS
        for w in overlay.describe_template(template_id)["workflows"]
        for c in w["collections"]
        if c["edit"] == "regex" and c["wildcards"]
    ]
    if not with_wildcards:
        pytest.skip("no shipped scan names a wildcard")
    template_id, tag, _ = with_wildcards[0]
    with pytest.raises(BuilderRefused, match="must keep"):
        overlay.compose(
            template_id, TemplateEdits(scans={tag: ScanEdit(regex=r"plain\.tsv")}), remote=False
        )


@pytest.mark.parametrize("template_id", ["../etc", "/abs/path", "nf-core/nope/1.0.0"])
def test_only_a_shipped_template_is_read(template_id):
    with pytest.raises(BuilderRefused) as refused:
        overlay.describe_template(template_id)
    assert refused.value.status in (400, 404)


@pytest.mark.parametrize("template_id", IDS)
def test_a_fork_changes_the_repository_and_nothing_else(template_id):
    original = _load_yaml(str(dict(SHIPPED)[template_id]))
    first = original["workflows"][0]
    edits = TemplateEdits(
        workflows={
            first["name"]: WorkflowEdit(
                repository_url="https://github.com/lab/fork", engine_version="24.10.0"
            )
        }
    )
    raw, *_ = overlay.compose(template_id, edits, remote=False)

    workflow = raw["workflows"][0]
    assert workflow["repository_url"] == "https://github.com/lab/fork"
    assert workflow["engine"]["version"] == "24.10.0"
    # What the edit does not name stays as shipped.
    for key in ("name", "version", "catalog", "data_location", "data_collections"):
        assert workflow.get(key) == first.get(key), key
    assert raw["workflows"][1:] == original["workflows"][1:]


def test_an_emptied_repository_is_dropped():
    edits = TemplateEdits(workflows={"ampliseq": WorkflowEdit(repository_url="")})
    raw, *_ = overlay.compose(AMPLISEQ, edits, remote=False)
    assert "repository_url" not in raw["workflows"][0]
    assert not edits.is_empty()


def test_a_workflow_can_be_renamed_and_moved_to_another_version_and_catalog():
    edits = TemplateEdits(
        workflows={
            "ampliseq": WorkflowEdit(
                name="ampliseq-lab", version="2.18.0-lab", catalog_name="", catalog_url=""
            )
        },
        additions=_extra(workflow="ampliseq"),
    )
    raw, *_ = overlay.compose(AMPLISEQ, edits, remote=False)
    (workflow,) = raw["workflows"]
    assert (workflow["name"], workflow["version"]) == ("ampliseq-lab", "2.18.0-lab")
    assert "catalog" not in workflow
    # The builder's collections, added under the shipped name, land in it.
    assert "builder_extra" in [dc["data_collection_tag"] for dc in workflow["data_collections"]]
    assert overlay.renamed_workflows(edits) == {"ampliseq": "ampliseq-lab"}


@pytest.mark.parametrize(
    ("edit", "fragment"),
    [
        (WorkflowEdit(name="../x"), "not a workflow name"),
        (WorkflowEdit(name="has space"), "not a workflow name"),
        (WorkflowEdit(version=" "), "version cannot be empty"),
        (WorkflowEdit(catalog_url="ftp://x"), "catalog URL"),
    ],
)
def test_a_workflow_edit_that_does_not_fit_is_refused(edit, fragment):
    with pytest.raises(BuilderRefused) as refused:
        overlay.compose(AMPLISEQ, TemplateEdits(workflows={"ampliseq": edit}), remote=False)
    assert fragment in refused.value.detail


def test_an_unchanged_name_is_no_rename():
    edits = TemplateEdits(workflows={"ampliseq": WorkflowEdit(name="ampliseq")})
    assert overlay.renamed_workflows(edits) == {}
