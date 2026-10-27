"""Pure region logic of the genome browser: chromosome names, merge, next / previous, density."""

from __future__ import annotations

import polars as pl

from depictio.api.v1.services.jbrowse import regions

ORDER = ["chr1", "chr2", "chr3", "chrX", "chrM"]

_SCHEMA = {
    "chrom": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "score": pl.Float64,
    "label": pl.Utf8,
    "sample": pl.Utf8,
    "run": pl.Utf8,
    "source": pl.Utf8,
}


def _frame(rows: list[tuple], **extra) -> pl.DataFrame:
    """Rows of ``(chrom, start, end)`` in the common shape, one source by default."""
    n = len(rows)
    cols: dict = {
        "chrom": [r[0] for r in rows],
        "start": [r[1] for r in rows],
        "end": [r[2] for r in rows],
        "score": extra.get("score", [None] * n),
        "label": extra.get("label", [None] * n),
        "sample": extra.get("sample", [None] * n),
        "run": extra.get("run", [None] * n),
        "source": extra.get("source", ["peaks"] * n),
    }
    return pl.DataFrame(cols, schema=_SCHEMA)


class TestChromNames:
    def test_the_chr_prefix_is_ignored(self):
        assert regions.canonical_chrom("chr1") == "1"
        assert regions.canonical_chrom("Chr1") == "1"
        assert regions.canonical_chrom("CHR12") == "12"
        assert regions.canonical_chrom("1") == "1"
        assert regions.canonical_chrom("chrX") == "X"

    def test_the_mitochondrion_has_one_name(self):
        assert {regions.canonical_chrom(c) for c in ("chrM", "M", "MT", "chrMT")} == {"MT"}

    def test_the_expression_agrees_with_the_function(self):
        names = ["chr1", "1", "CHRX", "chrM", "MT", "M", "contig_5"]
        got = (
            pl.DataFrame({"c": names})
            .select(regions.canonical_expr(pl.col("c")).alias("c"))["c"]
            .to_list()
        )
        assert got == [regions.canonical_chrom(n) for n in names]

    def test_chrom_index_follows_the_assembly_order(self):
        assert regions.chrom_index(["chr1", "chr2", "chrM"]) == {"1": 0, "2": 1, "MT": 2}
        assert regions.chrom_index(["1", "chr1"]) == {"1": 0}

    def test_variants_cover_both_spellings(self):
        assert set(regions.chrom_name_variants(["chr1"])) == {"chr1", "1"}
        assert {"M", "chrM", "MT", "chrMT"} <= set(regions.chrom_name_variants("MT"))


class TestNear:
    DF = _frame(
        [
            ("1", 100, 200),
            ("1", 500, 600),
            ("1", 900, 950),
            ("3", 50, 80),
            ("3", 300, 400),
            ("chr7", 10, 20),
        ]
    )

    def _near(self, chrom, pos, direction):
        row = regions.near_region(self.DF, chrom, pos, direction, ORDER)
        return None if row is None else (row["chrom"], row["start"])

    def test_the_next_region_on_the_same_chromosome(self):
        assert self._near("chr1", 150, 1) == ("1", 500)
        assert self._near("chr1", 500, 1) == ("1", 900)

    def test_chr_prefix_does_not_matter(self):
        assert self._near("1", 150, 1) == ("1", 500)

    def test_the_previous_region_ends_before_the_position(self):
        assert self._near("chr1", 700, -1) == ("1", 500)
        assert self._near("chr1", 590, -1) == ("1", 100)

    def test_past_the_last_region_it_moves_to_the_next_chromosome(self):
        # chr2 has no region: it is skipped.
        assert self._near("chr1", 900, 1) == ("3", 50)

    def test_before_the_first_region_it_moves_to_the_previous_chromosome(self):
        assert self._near("chr3", 40, -1) == ("1", 900)
        assert regions.near_region(self.DF, "chr3", 40, -1, ORDER)["end"] == 950

    def test_chromosomes_missing_from_the_assembly_are_skipped(self):
        # chr7 is in the data but not in the order: there is nothing after chr3.
        assert self._near("chr3", 300, 1) is None

    def test_the_ends_do_not_wrap(self):
        assert self._near("chr1", 50, -1) is None
        assert self._near("chrX", 5, 1) is None

    def test_an_unknown_chromosome_has_no_neighbour(self):
        assert self._near("chrZ", 5, 1) is None

    def test_rows_without_coordinates_are_ignored(self):
        broken = pl.DataFrame(
            {
                "chrom": ["1"],
                "start": [None],
                "end": [None],
                "score": [None],
                "label": [None],
                "sample": [None],
                "run": [None],
                "source": ["peaks"],
            },
            schema=_SCHEMA,
        )
        df = _frame([("1", 100, 200)]).vstack(broken)
        assert regions.near_region(df, "chr1", 0, 1, ORDER)["start"] == 100
        assert regions.near_region(df, "chr1", 100, 1, ORDER) is None


class TestMerge:
    def test_overlapping_samples_become_one_region(self):
        df = _frame(
            [("chr1", 100, 200), ("chr1", 150, 260), ("chr1", 240, 300), ("chr1", 900, 950)],
            sample=["S1", "S2", "S1", "S3"],
            score=[5.0, 9.0, 1.0, 2.0],
            label=["a", "b", "c", "d"],
        )
        out = regions.merge_regions(df, descending=True)
        assert out.height == 2
        first, second = out.to_dicts()
        assert (first["start"], first["end"]) == (100, 300)
        assert first["score"] == 9.0 and first["label"] == "b"
        assert first["n_rows"] == 3 and first["n_samples"] == 2
        assert first["samples"] == ["S1", "S2"] and first["sample"] is None
        assert (second["start"], second["end"], second["sample"]) == (900, 950, "S3")

    def test_the_best_score_is_the_smallest_when_ascending(self):
        df = _frame([("1", 1, 10), ("1", 5, 20)], score=[0.5, 0.01], label=["x", "y"])
        out = regions.merge_regions(df, descending=False).row(0, named=True)
        assert out["score"] == 0.01 and out["label"] == "y"

    def test_no_scores_gives_a_null_score_and_the_first_label(self):
        df = _frame([("1", 1, 10), ("1", 5, 20)], label=["x", "y"])
        out = regions.merge_regions(df).row(0, named=True)
        assert out["score"] is None and out["label"] == "x"

    def test_sources_are_never_merged_together(self):
        # A long region of one source (a copy-number segment) must not swallow
        # the regions of another; overlaps join within a source only.
        df = _frame(
            [("1", 100, 200), ("chr1", 180, 400), ("2", 100, 200)],
            source=["peaks", "genes", "genes"],
            sample=["S1", None, None],
        )
        out = regions.merge_regions(df).to_dicts()
        assert [(r["chrom"], r["start"], r["end"]) for r in out] == [
            ("1", 100, 200),
            ("chr1", 180, 400),
            ("2", 100, 200),
        ]
        assert [r["sources"] for r in out] == [["peaks"], ["genes"], ["genes"]]
        assert out[0]["n_samples"] == 1 and out[1]["n_samples"] == 0 and out[1]["samples"] == []

    def test_chr_spelling_does_not_split_a_region(self):
        df = _frame([("chr1", 100, 200), ("1", 150, 250)])
        assert regions.merge_regions(df).height == 1

    def test_regions_come_out_in_karyotype_order(self):
        df = _frame([("chr10", 1, 2), ("chr2", 1, 2), ("chrX", 1, 2), ("chr1", 1, 2)])
        assert regions.merge_regions(df)["chrom"].to_list() == ["chr1", "chr2", "chr10", "chrX"]

    def test_at_most_ten_sample_names_are_listed(self):
        df = _frame([("1", 1, 100)] * 15, sample=[f"S{i}" for i in range(15)])
        out = regions.merge_regions(df).row(0, named=True)
        assert out["n_samples"] == 15 and len(out["samples"]) == 10

    def test_an_empty_frame_merges_to_nothing(self):
        assert regions.merge_regions(_frame([])).height == 0

    def test_a_gap_keeps_regions_apart(self):
        df = _frame([("1", 1, 10), ("1", 12, 20)])
        assert regions.merge_regions(df).height == 2


class TestSourceFrame:
    RAW = pl.DataFrame(
        {
            "chr": ["chr1", "chr2", None],
            "s": ["300", "100", "5"],
            "e": [200, 150, 9],
            "p": [0.1, 0.2, 0.3],
            "name": ["a", None, "c"],
            "lib": ["L1", "L2", "L1"],
            "fc": [1, 2, 3],
        },
    )
    SPEC = {
        "name": "peaks",
        "chrom_column": "chr",
        "start_column": "s",
        "end_column": "e",
        "sort_by": "p",
        "label_column": "name",
        "sample_column": "lib",
        "columns": ["fc"],
        "search_columns": ["fc", "lib"],
    }

    def test_the_common_shape(self):
        out = regions.source_frame(self.RAW, self.SPEC)
        assert out.columns == [
            "chrom",
            "start",
            "end",
            "score",
            "label",
            "sample",
            "run",
            "source",
            "x:fc",
            "s:lib",
        ]
        first = out.row(0, named=True)
        # start and end are put in order
        assert (first["start"], first["end"]) == (200, 300)
        assert first["source"] == "peaks" and first["sample"] == "L1" and first["x:fc"] == 1
        assert out["run"].to_list() == [None, None, None]

    def test_a_missing_end_column_means_a_point(self):
        spec = {**self.SPEC, "end_column": None}
        out = regions.source_frame(self.RAW, spec)
        assert (out["start"][1], out["end"][1]) == (100, 100)

    def test_a_missing_column_reads_as_null_and_keeps_the_rows(self):
        out = regions.source_frame(self.RAW, {**self.SPEC, "start_column": "nope"})
        assert out.height == 3 and out["start"].null_count() == 3

    def test_the_mate_is_read_for_the_primary_only(self):
        raw = pl.DataFrame({"c": ["1"], "s": [1], "c2": ["9"], "s2": [40]})
        spec = {
            "name": "f",
            "chrom_column": "c",
            "start_column": "s",
            "mate": {"chrom_column": "c2", "start_column": "s2"},
        }
        assert "_mchrom" not in regions.source_frame(raw, spec).columns
        out = regions.source_frame(raw, spec, is_primary=True).row(0, named=True)
        assert (out["_mchrom"], out["_mstart"], out["_mend"]) == ("9", 40, 40)

    def test_several_sources_stack(self):
        a = regions.source_frame(self.RAW, self.SPEC)
        b = regions.source_frame(
            pl.DataFrame({"c": ["1"], "s": [5], "e": [8]}),
            {"name": "genes", "chrom_column": "c", "start_column": "s", "end_column": "e"},
        )
        both = regions.union_frames([a, b])
        assert both.height == 4 and both["source"].to_list()[-1] == "genes"
        assert both["x:fc"].to_list()[-1] is None


class TestSortAndSearch:
    A = {
        "name": "peaks",
        "chrom_column": "chr",
        "start_column": "s",
        "sort_by": "p",
        "label_column": "name",
        "sample_column": "lib",
        "columns": ["fc"],
        "search_columns": ["fc"],
    }
    B = {
        "name": "genes",
        "chrom_column": "c",
        "start_column": "pos",
        "sort_by": "padj",
        "label_column": "gene",
        "columns": ["fc"],
    }

    def test_raw_and_common_names_are_both_sortable(self):
        names = regions.sortable_columns([self.A, self.B])
        assert {"chrom", "start", "score", "sample", "p", "padj", "lib", "fc", "gene"} <= set(names)
        assert "n_samples" not in names
        assert "n_samples" in regions.sortable_columns([self.A], merged=True)

    def test_a_raw_column_maps_onto_the_common_shape(self):
        df = pl.DataFrame(
            {
                "score": [0.3, 0.1],
                "x:fc": [1, 2],
                "source": ["peaks", "peaks"],
                "chrom": ["1", "2"],
                "start": [1, 2],
            }
        )
        (key,) = regions.sort_keys(df, [self.A], "p")
        assert df.select(key).columns == ["score"]
        (key,) = regions.sort_keys(df, [self.A], "fc")
        assert df.select(key).columns == ["x:fc"]

    def test_a_column_read_from_different_columns_sorts_as_text(self):
        df = pl.DataFrame({"score": [0.3, 0.1], "source": ["peaks", "genes"], "x:fc": [1, 2]})
        a = {**self.A, "columns": [], "sort_by": "fc"}
        b = {**self.B, "columns": ["fc"], "sort_by": None}
        (key,) = regions.sort_keys(df, [a, b], "fc")
        assert df.select(key)["_sort"].to_list() == ["0.3", "2"]

    def test_an_unknown_column_has_no_key(self):
        df = pl.DataFrame({"chrom": ["1"], "start": [1], "source": ["peaks"]})
        assert regions.sort_keys(df, [self.A], "nope") is None
        assert regions.sort_keys(df, [self.A], "n_samples", merged=False) is None
        assert regions.sort_keys(df, [self.A], "n_samples", merged=True) is not None

    def test_chromosomes_sort_in_karyotype_order(self):
        df = pl.DataFrame({"chrom": ["chr10", "chr2", "chrX"], "start": [1, 1, 1]})
        keys = regions.sort_keys(df, [self.A], "chrom")
        assert regions.sort_calls(df, keys, False)["chrom"].to_list() == ["chr2", "chr10", "chrX"]
        assert regions.sort_calls(df, keys, True)["chrom"].to_list() == ["chrX", "chr10", "chr2"]

    def test_nulls_sort_last_either_way(self):
        df = pl.DataFrame({"score": [2.0, None, 1.0]})
        keys = [pl.col("score")]
        assert regions.sort_calls(df, keys, False)["score"].to_list() == [1.0, 2.0, None]
        assert regions.sort_calls(df, keys, True)["score"].to_list() == [2.0, 1.0, None]

    def test_search_reads_the_label_and_the_search_columns_of_each_source(self):
        df = pl.DataFrame(
            {
                "source": ["peaks", "peaks", "genes"],
                "label": ["Alpha", "beta", "gamma"],
                "x:fc": ["up", "down", "up"],
            }
        )
        mask = regions.search_mask(df, [self.A, self.B], "UP")
        # fc is searched on peaks (a search column) but not on genes
        assert df.select(mask.alias("m"))["m"].to_list() == [True, False, False]
        mask = regions.search_mask(df, [self.A, self.B], "gam")
        assert df.select(mask.alias("m"))["m"].to_list() == [False, False, True]

    def test_a_blank_search_matches_everything(self):
        df = pl.DataFrame({"source": ["peaks"], "label": [None]})
        assert df.select(regions.search_mask(df, [self.A], "  ").alias("m"))["m"].to_list() == [
            True
        ]


    def test_column_filters_take_text_and_number_ops(self):
        df = pl.DataFrame(
            {
                "source": ["peaks"] * 3,
                "label": ["Alpha", "beta", "Gamma"],
                "chrom": ["chr1", "chr2", "chr1"],
                "start": [1, 2, 3],
                "score": [0.5, 2.0, 7.5],
            }
        )

        def kept(filters):
            return df.filter(regions.column_filter_mask(df, [self.A], filters))["label"].to_list()

        assert kept([{"column": "label", "kind": "text", "op": "contains", "value": "AM"}]) == [
            "Gamma"
        ]
        assert kept([{"column": "chrom", "kind": "text", "op": "equals", "value": "chr1"}]) == [
            "Alpha",
            "Gamma",
        ]
        assert kept(
            [{"column": "score", "kind": "number", "op": "greaterThan", "value": 1.0}]
        ) == ["beta", "Gamma"]
        both = [
            {"column": "chrom", "kind": "text", "op": "equals", "value": "chr1"},
            {"column": "score", "kind": "number", "op": "inRange", "value": 0, "value_to": 1},
        ]
        assert kept(both) == ["Alpha"]
        # A raw column name maps onto the common shape, as for a sort.
        assert kept([{"column": "p", "kind": "number", "op": "lessThan", "value": 1}]) == ["Alpha"]

    def test_an_unknown_filter_column_keeps_every_row(self):
        df = pl.DataFrame({"source": ["peaks"], "label": ["a"], "chrom": ["1"], "start": [1]})
        mask = regions.column_filter_mask(
            df, [self.A], [{"column": "nope", "kind": "text", "op": "contains", "value": "x"}]
        )
        assert df.filter(mask).height == 1


class TestDensity:
    REGIONS = [{"refName": "chr1", "length": 1000}, {"refName": "chr2", "length": 500}]

    def test_the_bin_size_spreads_the_genome_over_the_bins(self):
        assert regions.bin_size_for(self.REGIONS, 500) == 3
        assert regions.bin_size_for(self.REGIONS, 5000) == 1
        assert regions.bin_size_for([], 100) == 1

    def test_counts_per_bin_per_region_with_chr_tolerance(self):
        df = _frame([("1", 5, 6), ("chr1", 15, 16), ("1", 17, 18), ("2", 499, 500), ("9", 1, 2)])
        out = regions.density(df, self.REGIONS, 10)
        assert out["bin_size"] == 10 and out["truncated"] == 0
        (track,) = out["tracks"]
        assert track["label"] == "peaks" and track["run"] is None
        chr1, chr2 = track["chroms"]
        assert (chr1["refName"], len(chr1["counts"])) == ("chr1", 100)
        assert chr1["counts"][0] == 1 and chr1["counts"][1] == 2
        assert (chr2["refName"], len(chr2["counts"]), chr2["counts"][49]) == ("chr2", 50, 1)
        assert out["max"] == 2

    def test_a_row_past_the_end_counts_in_the_last_bin(self):
        out = regions.density(_frame([("chr2", 9999, 10000)]), self.REGIONS, 100)
        assert out["tracks"][0]["chroms"][1]["counts"] == [0, 0, 0, 0, 1]

    def test_one_track_per_source_in_source_order_even_when_empty(self):
        df = _frame([("1", 5, 6), ("1", 7, 8)], source=["genes", "genes"])
        out = regions.density(df, self.REGIONS, 100, source_order=["peaks", "genes"])
        assert [t["source"] for t in out["tracks"]] == ["peaks", "genes"]
        assert out["tracks"][0]["chroms"][0]["counts"] == [0] * 10
        assert out["tracks"][1]["chroms"][0]["counts"][0] == 2

    def test_sample_tracks_carry_their_run_and_sources_without_samples_stay_whole(self):
        df = _frame(
            [("1", 5, 6), ("1", 6, 7), ("1", 8, 9), ("1", 9, 9)],
            source=["peaks", "peaks", "peaks", "genes"],
            sample=["S1", "S2", "S1", None],
            run=["r1", "r2", "r1", None],
        )
        out = regions.density(
            df, self.REGIONS, 100, group="sample", source_order=["peaks", "genes"]
        )
        got = [(t["source"], t["label"], t["run"]) for t in out["tracks"]]
        assert got == [("peaks", "S1", "r1"), ("peaks", "S2", "r2"), ("genes", "genes", None)]
        assert out["tracks"][0]["chroms"][0]["counts"][0] == 2

    def test_run_tracks(self):
        df = _frame([("1", 5, 6), ("1", 6, 7)], run=["r1", "r2"])
        out = regions.density(df, self.REGIONS, 100, group="run")
        assert [(t["label"], t["run"]) for t in out["tracks"]] == [("r1", None), ("r2", None)]

    def test_the_track_cap_keeps_the_busiest_in_first_seen_order(self):
        samples = [f"S{i}" for i in range(70)]
        rows = [("1", i, i + 1) for i in range(70)]
        # S0..S69 have one row each; S5 gets four more and S60 two more.
        extra = [("1", 1, 2)] * 4 + [("1", 2, 3)] * 2
        df = _frame(rows + extra, sample=samples + ["S5"] * 4 + ["S60"] * 2)
        out = regions.density(df, self.REGIONS, 100, group="sample")
        labels = [t["label"] for t in out["tracks"]]
        assert len(labels) == 64 and out["truncated"] == 6
        assert "S5" in labels and "S60" in labels
        assert labels == sorted(labels, key=lambda s: int(s[1:]))
        assert out["max"] == 5
