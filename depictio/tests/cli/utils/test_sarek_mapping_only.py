"""A sarek run that stopped after mapping: what the template ingests and which tabs survive.

The run-folder tree below carries the file names of the ``mapping_only`` subset of
``megatest.yaml`` (no VCF, no bcftools / vcftools / snpEff report, no
``csv/variantcalled.csv``). The preview says which collections find their inputs;
the dashboard engine's own pruning then decides, from that, which tabs the import
keeps. Nothing is created: no server, no Mongo.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

# The CLI job installs the base package only; the dashboard routes need the server extra.
pytest.importorskip("fastapi")
pytest.importorskip("cryptography")

import depictio.api.v1.endpoints.dashboards_endpoints.routes as routes  # noqa: E402
from depictio.cli.cli.utils.template_preview import preview_data_root
from depictio.tests.cli.s3_stubs import write_tree

TEMPLATE_ID = "nf-core/sarek/3.10.0"
ROOT = Path(__file__).resolve().parents[3] / "projects/nf-core/sarek/3.10.0"

_RECALIBRATED = (
    "patient,sex,status,sample,cram,crai\n"
    "P1,NA,0,S1,preprocessing/recalibrated/S1/S1.recal.cram,"
    "preprocessing/recalibrated/S1/S1.recal.cram.crai\n"
)
_CALLED = "patient,sample,variantcaller,vcf\nP1,S1,haplotypecaller,variant_calling/x.vcf.gz\n"

_MAPPING_FILES = [
    "pipeline_info/params_2026-01-01_00-00-00.json",
    "multiqc/multiqc_data/multiqc.parquet",
    "multiqc/multiqc_data/mosdepth-xy-coverage-plot.txt",
    "reports/mosdepth/S1/S1.recal.mosdepth.summary.txt",
    "reports/mosdepth/S1/S1.recal.mosdepth.region.dist.txt",
    "reports/mosdepth/S1/S1.recal.mosdepth.global.dist.txt",
    "reports/mosdepth/S1/S1.recal.regions.bed.gz",
    "reports/mosdepth/S1/S1.md.mosdepth.summary.txt",
    "reports/mosdepth/S1/S1.md.mosdepth.region.dist.txt",
    "reports/mosdepth/S1/S1.md.mosdepth.global.dist.txt",
    "reports/mosdepth/S1/S1.md.regions.bed.gz",
]
_CALLED_FILES = [
    "variant_calling/haplotypecaller/S1/S1.haplotypecaller.filtered.vcf.gz",
    "variant_calling/deepvariant/S1/S1.deepvariant.vcf.gz",
    "reports/bcftools/haplotypecaller/S1/S1.haplotypecaller.filtered.bcftools_stats.txt",
    "reports/vcftools/haplotypecaller/S1/S1.haplotypecaller.filtered.TsTv.qual",
    "reports/vcftools/haplotypecaller/S1/S1.haplotypecaller.filtered.TsTv.count",
    "reports/vcftools/haplotypecaller/S1/S1.haplotypecaller.filtered.FILTER.summary",
    "annotation/haplotypecaller/S1/S1.haplotypecaller.filtered_snpEff.ann.vcf.gz",
    "reports/snpeff/haplotypecaller/S1/S1.haplotypecaller.filtered_snpEff.csv",
    "reports/snpeff/haplotypecaller/S1/S1.haplotypecaller.filtered_snpEff.genes.txt",
]
_SV_FILES = ["variant_calling/manta/S1/S1.manta.diploid_sv.vcf.gz"]
# A tumour/normal pair as `-profile test --tools strelka,mutect2,cnvkit,msisensorpro` writes it:
# the pair's files are named after `<tumour>_vs_<normal>`.
_PAIR_FILES = [
    "variant_calling/mutect2/T1_vs_S1/T1_vs_S1.mutect2.filtered.vcf.gz",
    "variant_calling/strelka/T1_vs_S1/T1_vs_S1.strelka.somatic_snvs.vcf.gz",
    "variant_calling/strelka/T1_vs_S1/T1_vs_S1.strelka.somatic_indels.vcf.gz",
]
_COPY_NUMBER_FILES = [
    "variant_calling/cnvkit/T1_vs_S1/T1.somatic.call.cns",
    "variant_calling/cnvkit/T1_vs_S1/T1.cnr",
    "variant_calling/msisensorpro/T1_vs_S1/T1_vs_S1",
]

#: The tabs a run that called variants, annotated them and ran an SV caller keeps.
ALL_TABS = {
    "Overview",
    "MultiQC",
    "Coverage",
    "Variant yield",
    "Call quality",
    "Caller concordance",
    "Structural variants",
    "Consequences",
    "Genes",
    "Protein",
    "Locus",
}
MAPPING_TABS = {"Overview", "MultiQC", "Coverage", "Locus"}
#: The Somatic group. A tab appears only when a collection it reads holds rows.
SOMATIC_TABS = {"Somatic calls", "Copy number & MSI", "Germline vs somatic"}
#: The collections the Somatic tabs read. The preview counts files, not rows, so these are
#: "present" as soon as their source files are (the VCFs, the sample sheet); whether they
#: hold a row is the recipes' job (test_sarek_somatic.py: each raises on a run without
#: the calls it needs, which skips the optional collection at ingestion).
SOMATIC_DCS = {
    "pairs",
    "somatic_calls",
    "somatic_vs_germline",
    "patient_call_counts",
    "somatic_variants",
    "somatic_burden",
    "germline_het_sites",
    "cnv_segments",
    "msi",
}
#: The collections built on the pairs' PASS variants: each recipe raises without a pair
#: that has somatic calls (and ``germline_het_sites`` without a jointly genotyped one).
PAIR_VARIANT_DCS = {"somatic_variants", "somatic_burden", "germline_het_sites"}
#: The collections every run holds, whatever its tools.
REQUIRED = {"samples", "tracks", "multiqc_data"}
DC_ID = "646b0f3c1e4a2d7f8e5b8ca9"


@pytest.fixture(autouse=True)
def cli_context(monkeypatch):
    monkeypatch.setenv("DEPICTIO_CONTEXT", "CLI")
    monkeypatch.delenv("DEPICTIO_LOCAL_DATA_ROOTS", raising=False)
    monkeypatch.delenv("DEPICTIO_AUTH_SINGLE_USER_MODE", raising=False)


def _tree(tmp_path: Path, *groups: list[str], called: bool = False) -> Path:
    files: dict[str, bytes] = {rel: b"x\n" for rel in _MAPPING_FILES}
    for group in groups:
        files.update({rel: b"x\n" for rel in group})
    files["pipeline_info/params_2026-01-01_00-00-00.json"] = b"{}\n"
    files["csv/recalibrated.csv"] = _RECALIBRATED.encode()
    if called:
        files["csv/variantcalled.csv"] = _CALLED.encode()
    return write_tree(tmp_path / "run", files)


def _ok_tags(root: Path) -> set[str]:
    preview = preview_data_root(TEMPLATE_ID, str(root))
    return {d.tag for d in preview.data_collections if d.status == "ok"}


def _germline_only(present: set[str]) -> set[str]:
    """What a run with no tumour holds: every Somatic collection's recipe raises on it."""
    return present - SOMATIC_DCS


def _surviving_tabs(present: set[str], monkeypatch) -> set[str]:
    """The dashboard's tabs the import keeps when only ``present`` collections hold data."""
    doc = yaml.safe_load((ROOT / "dashboards/base.yaml").read_text(encoding="utf-8"))
    template = yaml.safe_load((ROOT / "template.yaml").read_text(encoding="utf-8"))
    dcs = {d["data_collection_tag"]: d for d in template["workflows"][0]["data_collections"]}
    meta = {
        tag: {
            "type": str(dcs[tag]["config"]["type"]).lower(),
            "metatype": dcs[tag]["config"].get("metatype"),
            # Every collection in `present` has a delta table (the Mongo lookup an
            # optional one triggers is what `optional: False` leaves out).
            "optional": False,
        }
        for tag in present
    }
    monkeypatch.setattr(routes, "_build_dc_meta", lambda project_id: meta)
    main = doc["main_dashboard"]
    family = [("Overview", main)] + [(tab["title"], tab) for tab in doc["tabs"]]
    kept_tabs: set[str] = set()
    for title, head in family:
        components = copy.deepcopy(head["components"])
        for comp in components:
            tag = comp.get("data_collection_tag")
            if tag is not None:
                comp["dc_id"] = DC_ID if tag in present else None
            for value in (comp.get("values") or {}).values():
                value["dc_id"] = DC_ID if value["dc"] in present else None
        stored = {
            "stored_metadata": components,
            "right_panel_layout_data": [],
            "filter_sections": head.get("filter_sections"),
            "grid_sections": head.get("grid_sections"),
        }
        before = len(components)
        routes._filter_unresolved_components(stored, None)
        if len(stored["stored_metadata"]) == before or routes._tab_meets_minimum(
            stored, meta, True
        ):
            kept_tabs.add(title)
    return kept_tabs


def test_a_mapping_only_run_ingests_cleanly_and_skips_the_variant_chain(tmp_path):
    preview = preview_data_root(TEMPLATE_ID, str(_tree(tmp_path)))
    status = {d.tag: d.status for d in preview.data_collections}
    assert REQUIRED <= {tag for tag, s in status.items() if s == "ok"}
    assert {t for t in status if t.startswith("mosdepth_")} <= {
        tag for tag, s in status.items() if s == "ok"
    }
    for tag in (
        "bcftools_stats_summary",
        "vcf_calls_raw",
        "vcf_variants",
        "sv_calls",
        "callset_qc",
        "snpeff_ann_variants",
    ):
        assert status[tag] != "ok", tag


def test_a_mapping_only_run_keeps_the_overview_multiqc_coverage_and_locus_tabs(
    tmp_path, monkeypatch
):
    present = _ok_tags(_tree(tmp_path))
    assert _surviving_tabs(present, monkeypatch) == MAPPING_TABS


def test_a_run_that_called_variants_keeps_every_tab(tmp_path, monkeypatch):
    present = _germline_only(_ok_tags(_tree(tmp_path, _CALLED_FILES, _SV_FILES, called=True)))
    assert {"vcf_variants", "sv_calls", "callset_qc", "snpeff_ann_variants"} <= present
    tabs = _surviving_tabs(present, monkeypatch)
    assert tabs == ALL_TABS
    # A run with no tumour has no Somatic tab: the germline dashboard is unchanged.
    assert not tabs & SOMATIC_TABS


def test_without_an_sv_caller_only_the_structural_variants_tab_goes(tmp_path, monkeypatch):
    present = _germline_only(_ok_tags(_tree(tmp_path, _CALLED_FILES, called=True)))
    # The preview counts files, not rows: `sv_calls` settles as soon as its source
    # does, and it is the recipe that raises when no manta / tiddit VCF is among the
    # calls (test_sarek_sv_calls.py), which skips the collection at ingestion.
    assert "sv_calls" in present
    present.discard("sv_calls")
    assert _surviving_tabs(present, monkeypatch) == ALL_TABS - {"Structural variants"}


def test_a_tumour_normal_run_keeps_the_germline_tabs_and_adds_the_somatic_ones(
    tmp_path, monkeypatch
):
    present = _ok_tags(
        _tree(tmp_path, _CALLED_FILES, _SV_FILES, _PAIR_FILES, _COPY_NUMBER_FILES, called=True)
    )
    assert SOMATIC_DCS <= present
    assert _surviving_tabs(present, monkeypatch) == ALL_TABS | SOMATIC_TABS


def test_a_pair_whose_callers_found_nothing_keeps_only_the_copy_number_tab(tmp_path, monkeypatch):
    # The tiny `-profile test` run: the paired VCFs hold a header and no record, so
    # `somatic_calls` raises and takes `somatic_vs_germline` and `patient_call_counts`
    # with it; CNVkit and MSIsensor-pro still wrote their files. `pairs` is a design fact
    # and stays, but no tab is built on it alone.
    present = _ok_tags(
        _tree(tmp_path, _CALLED_FILES, _SV_FILES, _PAIR_FILES, _COPY_NUMBER_FILES, called=True)
    )
    present -= {"somatic_calls", "somatic_vs_germline", "patient_call_counts", "sv_calls"}
    present -= PAIR_VARIANT_DCS
    assert {"pairs", "cnv_segments", "msi"} <= present
    tabs = _surviving_tabs(present, monkeypatch)
    assert tabs == (ALL_TABS - {"Structural variants"}) | {"Copy number & MSI"}
    assert not tabs & {"Somatic calls", "Germline vs somatic"}


def test_a_pair_without_a_jointly_genotyped_caller_keeps_both_somatic_tabs(tmp_path, monkeypatch):
    # No Freebayes on the pair: `germline_het_sites` raises (no loss-of-heterozygosity
    # section) and, with no capture target, `somatic_burden` may be absent too. The two
    # tabs still stand on the variants and the call table.
    present = _ok_tags(
        _tree(tmp_path, _CALLED_FILES, _SV_FILES, _PAIR_FILES, _COPY_NUMBER_FILES, called=True)
    )
    present -= {"germline_het_sites", "somatic_burden"}
    assert {"somatic_variants", "somatic_vs_germline"} <= present
    assert {"Somatic calls", "Germline vs somatic"} <= _surviving_tabs(present, monkeypatch)


def test_a_tumour_called_on_its_own_has_no_comparison_with_a_normal(tmp_path, monkeypatch):
    # No pair on the sheet: `pairs` raises, and `somatic_vs_germline` and
    # `patient_call_counts` (both read it) with it. The tumour's own calls remain.
    present = _ok_tags(_tree(tmp_path, _CALLED_FILES, _SV_FILES, _COPY_NUMBER_FILES, called=True))
    present -= {"pairs", "somatic_vs_germline", "patient_call_counts"} | PAIR_VARIANT_DCS
    assert {"somatic_calls", "cnv_segments"} <= present
    tabs = _surviving_tabs(present, monkeypatch)
    assert {"Somatic calls", "Copy number & MSI"} <= tabs
    assert "Germline vs somatic" not in tabs


def test_a_mapping_only_run_has_no_somatic_collection(tmp_path):
    preview = preview_data_root(TEMPLATE_ID, str(_tree(tmp_path)))
    status = {d.tag: d.status for d in preview.data_collections}
    for tag in ("cnv_segments", "msi", "cnvkit_segments_raw", "msisensorpro_raw"):
        assert status[tag] != "ok", tag
