"""`nf-core/ampliseq/read_tracking.py` and `beta_adonis.py` across the routes' layouts.

`overall_summary.tsv` changes columns with the route (PacBio and IonTorrent stop
at `nonchim`, multiregion writes NA for the taxa filter, `--skip_cutadapt` drops
the cutadapt columns), and the adonis tables hold one header name fewer than the
rows hold fields. Both recipes have to read every variant.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from depictio.recipes import RecipeError, execute_recipe

READ_TRACKING = "nf-core/ampliseq/read_tracking.py"
BETA_ADONIS = "nf-core/ampliseq/beta_adonis.py"


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _row(df, sample: str) -> dict:
    return df.filter(df["sample"] == sample).to_dicts()[0]


def test_the_last_filter_with_a_value_is_what_the_run_kept(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "overall_summary.tsv",
        "sample\tcutadapt_total_processed\tcutadapt_passing_filters\tDADA2_input\tnonchim"
        "\tlenfilter_output\tinput_tax_filter\tfiltered_tax_filter\tretained_percent\n"
        "s1\t2,000\t1,800\t1800\t1200\t1100\t1100\t1000\t90.9\n"
        # Multiregion: the taxa filter wrote NA, so the length filter is the last step.
        "s2\t1,000\t900\t900\t600\t500\tNA\tNA\tNA\n",
    )
    out = execute_recipe(READ_TRACKING, tmp_path)

    s1, s2 = _row(out, "s1"), _row(out, "s2")
    assert (s1["input_reads"], s1["trimmed_reads"], s1["denoised_reads"]) == (2000, 1800, 1200)
    assert s1["final_reads"] == 1000
    assert s1["kept_percent"] == pytest.approx(50.0)
    assert s2["final_reads"] == 500
    assert s2["kept_percent"] == pytest.approx(50.0)


def test_a_run_that_stops_at_denoising_keeps_its_denoised_reads(tmp_path: Path) -> None:
    # PacBio / IonTorrent layout: no filter after DADA2.
    _write(
        tmp_path,
        "overall_summary.tsv",
        "sample\tcutadapt_total_processed\tcutadapt_passing_filters\tcutadapt_passing_filters_percent"
        "\tDADA2_input\tfiltered\tdenoised\tnonchim\n"
        "pb1\t2,000\t1,638\t81.9%\t1638\t1527\t1193\t1193\n",
    )
    row = _row(execute_recipe(READ_TRACKING, tmp_path), "pb1")
    assert row["final_reads"] == row["denoised_reads"] == 1193
    assert row["kept_percent"] == pytest.approx(59.65)


def test_without_cutadapt_the_dada2_input_is_the_input(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "overall_summary.tsv",
        "sample\tDADA2_input\tfiltered\tnonchim\ns1\t500\t450\t400\n",
    )
    out = execute_recipe(READ_TRACKING, tmp_path)
    assert "trimmed_reads" not in out.columns
    assert _row(out, "s1")["input_reads"] == 500
    assert _row(out, "s1")["kept_percent"] == pytest.approx(80.0)


_ADONIS_HEADER = "Df\tSumOfSqs\tR2\tF\tPr(>F)\n"


def test_adonis_keeps_the_term_rows_with_metric_and_formula(tmp_path: Path) -> None:
    base = "qiime2/diversity/beta_diversity/adonis"
    _write(
        tmp_path,
        f"{base}/bray_curtis_distance_matrix-habitat/adonis.tsv",
        _ADONIS_HEADER + "habitat\t3\t4.0\t0.94\t41.8\t0.001\n"
        "Residual\t8\t0.26\t0.06\tNA\tNA\nTotal\t11\t4.26\t1\tNA\tNA\n",
    )
    # A two-term formula writes one row per term.
    _write(
        tmp_path,
        f"{base}/jaccard_distance_matrix-site+season/adonis.tsv",
        _ADONIS_HEADER + "site\t1\t1.0\t0.5\t10\t0.01\nseason\t1\t0.2\t0.1\t2\t0.2\n"
        "Residual\t8\t0.8\t0.4\tNA\tNA\nTotal\t10\t2.0\t1\tNA\tNA\n",
    )
    out = execute_recipe(BETA_ADONIS, tmp_path)

    assert out.height == 3
    assert set(out["term"]) == {"habitat", "site", "season"}
    habitat = out.filter(out["term"] == "habitat").to_dicts()[0]
    assert (habitat["metric"], habitat["formula"]) == ("bray_curtis", "habitat")
    assert habitat["r2"] == pytest.approx(0.94)
    assert habitat["p_value"] == pytest.approx(0.001)
    assert habitat["df"] == 3
    assert set(out.filter(out["metric"] == "jaccard")["formula"]) == {"site+season"}


def test_adonis_with_a_group_col_keeps_that_term_only(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "qiime2/diversity/beta_diversity/adonis/bray_curtis_distance_matrix-site+season/adonis.tsv",
        _ADONIS_HEADER + "site\t1\t1.0\t0.5\t10\t0.01\nseason\t1\t0.2\t0.1\t2\t0.2\n"
        "Residual\t8\t0.8\t0.4\tNA\tNA\nTotal\t10\t2.0\t1\tNA\tNA\n",
    )
    out = execute_recipe(BETA_ADONIS, tmp_path, params={"group_col": "season"})
    assert out["term"].to_list() == ["season"]
    assert out["r2"].to_list() == [pytest.approx(0.1)]

    # The no-metadata sentinel names no term, so the optional DC is skipped.
    with pytest.raises(RecipeError, match="empty"):
        execute_recipe(BETA_ADONIS, tmp_path, params={"group_col": "__no_group__"})
    # An unset variable keeps every term.
    unset = execute_recipe(BETA_ADONIS, tmp_path, params={"group_col": "{GROUP_COL}"})
    assert unset.height == 2
