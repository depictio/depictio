"""Which params*.json the template-variable introspection reads.

A resumed run writes one params file per attempt, so a results directory
routinely holds several and only the last describes the run that produced the
outputs. These tests pin that choice, because getting it wrong is silent: the
flags still resolve, they just describe an abandoned attempt, and the template
prunes the wrong data collections.
"""

import json

from depictio.cli.cli.utils.templates import _introspect_pipeline_params
from depictio.models.models.nextflow import params_files_newest_first


def _write_params(directory, name, payload):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(json.dumps(payload))


class TestNewestParamsWins:
    def test_later_attempt_overrides_the_first(self, tmp_path):
        """The run was resumed with skip_taxonomy off, so the flag must not be set."""
        info = tmp_path / "pipeline_info"
        _write_params(info, "params_2026-06-11_16-37-38.json", {"skip_taxonomy": True})
        _write_params(info, "params_2026-06-12_07-20-45.json", {"skip_taxonomy": False})

        variables: dict[str, str] = {}
        _introspect_pipeline_params(str(tmp_path), variables)

        assert "SKIP_TAXONOMY" not in variables

    def test_later_attempt_can_add_a_flag(self, tmp_path):
        """The mirror case, so the test cannot pass by simply reading nothing."""
        info = tmp_path / "pipeline_info"
        _write_params(info, "params_2026-06-11_16-37-38.json", {"skip_taxonomy": False})
        _write_params(info, "params_2026-06-12_07-20-45.json", {"skip_taxonomy": True})

        variables: dict[str, str] = {}
        _introspect_pipeline_params(str(tmp_path), variables)

        assert variables["SKIP_TAXONOMY"] == "true"

    def test_unparseable_newest_falls_through(self, tmp_path):
        """A run killed mid-write leaves a truncated file; the previous one still counts."""
        info = tmp_path / "pipeline_info"
        _write_params(info, "params_2026-06-11_16-37-38.json", {"platform": "nanopore"})
        info.joinpath("params_2026-06-12_07-20-45.json").write_text('{"platform": "nano')

        variables: dict[str, str] = {}
        _introspect_pipeline_params(str(tmp_path), variables)

        assert variables["IS_NANOPORE"] == "true"


class TestWhereItLooks:
    def test_sequencing_runs_layout_one_level_down(self, tmp_path):
        """DATA_ROOT aggregating run_*/ subdirs: params sits inside a run."""
        _write_params(
            tmp_path / "run_A" / "pipeline_info",
            "params_2026-01-01_00-00-00.json",
            {"protocol": "metagenomic"},
        )

        variables: dict[str, str] = {}
        _introspect_pipeline_params(str(tmp_path), variables)

        assert variables["IS_METAGENOMIC"] == "true"

    def test_params_file_run_shape_is_recognised(self, tmp_path):
        """A `-params-file` run writes nf-params.json, which the old glob missed."""
        _write_params(tmp_path / "pipeline_info", "nf-params.json", {"skip_qiime": True})

        variables: dict[str, str] = {}
        _introspect_pipeline_params(str(tmp_path), variables)

        assert variables["SKIP_QIIME"] == "true"

    def test_no_params_at_all_is_a_no_op(self, tmp_path):
        variables: dict[str, str] = {"GROUP_COL": "treatment"}
        _introspect_pipeline_params(str(tmp_path), variables)
        assert variables == {"GROUP_COL": "treatment"}


class TestExplicitVarsWin:
    def test_a_user_supplied_flag_is_never_overridden(self, tmp_path):
        _write_params(
            tmp_path / "pipeline_info", "params_2026-01-01_00-00-00.json", {"skip_qiime": True}
        )

        variables = {"SKIP_QIIME": "false"}
        _introspect_pipeline_params(str(tmp_path), variables)

        assert variables["SKIP_QIIME"] == "false"


class TestPplaceTree:
    """The phylogenetic-placement route's only Newick is the EPA-ng graft under pplace/."""

    # run_pplace stays false on runs that pass the pplace_* inputs directly, as the
    # ampliseq test_pplace profile does, so the route must key on pplace_tree.
    PARAMS = {"pplace_tree": "https://example.org/ref.newick", "pplace_name": "run"}
    GRAFT = "run.graft.run.epa_result.newick"

    def _introspect(self, tmp_path, params, variables=None):
        _write_params(tmp_path / "pipeline_info", "params_2026-01-01_00-00-00.json", params)
        variables = {} if variables is None else variables
        _introspect_pipeline_params(str(tmp_path), variables)
        return variables

    def _touch(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("(a,b);")
        return path

    def test_graft_tree_is_picked_over_the_gappa_copy(self, tmp_path):
        graft = self._touch(tmp_path / "pplace" / self.GRAFT)
        self._touch(tmp_path / "pplace" / "gappa" / self.GRAFT)

        variables = self._introspect(tmp_path, {**self.PARAMS, "run_pplace": False})

        assert variables["PPLACE_TREE_FILE"] == str(graft)

    def test_no_graft_file_sets_nothing(self, tmp_path):
        (tmp_path / "pplace").mkdir()

        assert "PPLACE_TREE_FILE" not in self._introspect(tmp_path, self.PARAMS)

    def test_gappa_copy_alone_is_not_used(self, tmp_path):
        self._touch(tmp_path / "pplace" / "gappa" / self.GRAFT)

        assert "PPLACE_TREE_FILE" not in self._introspect(tmp_path, self.PARAMS)

    def test_explicit_value_is_kept(self, tmp_path):
        self._touch(tmp_path / "pplace" / self.GRAFT)

        variables = self._introspect(
            tmp_path, self.PARAMS, {"PPLACE_TREE_FILE": "/elsewhere/tree.newick"}
        )

        assert variables["PPLACE_TREE_FILE"] == "/elsewhere/tree.newick"

    def test_run_without_pplace_sets_nothing(self, tmp_path):
        """A stray graft file is not enough: the run itself must be a pplace run."""
        self._touch(tmp_path / "pplace" / self.GRAFT)

        variables = self._introspect(tmp_path, {"pplace_tree": None, "skip_qiime": False})

        assert "PPLACE_TREE_FILE" not in variables


class TestPhylumLevel:
    """QIIME2 names collapsed taxonomy by depth; the Phylum's depth follows the database."""

    RANKS = ("CLASS_LEVEL", "ORDER_LEVEL", "FAMILY_LEVEL", "GENUS_LEVEL")
    SBDI = {
        "dada_ref_taxonomy": "sbdi-gtdb",
        "dada_ref_databases": {
            "sbdi-gtdb": {"taxlevels": "Domain,Kingdom,Phylum,Class,Order,Family,Genus,Species"}
        },
        "tax_agglom_max": 6,
    }
    # Databases without a taxlevels entry take DADA2's 7-rank default.
    GTDB = {
        "dada_ref_taxonomy": "gtdb=R07-RS207",
        "dada_ref_databases": {"gtdb=R07-RS207": {"title": "GTDB"}},
        "tax_agglom_max": 2,
    }

    def _introspect(self, tmp_path, params=None, variables=None):
        if params is not None:
            _write_params(tmp_path / "pipeline_info", "params_2026-01-01_00-00-00.json", params)
        variables = {} if variables is None else variables
        _introspect_pipeline_params(str(tmp_path), variables)
        return variables

    def _write(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_seven_rank_database_capped_by_tax_agglom_max(self, tmp_path):
        variables = self._introspect(tmp_path, self.GTDB)

        assert variables["PHYLUM_LEVEL"] == "2"
        assert [variables[r] for r in self.RANKS] == ["3", "4", "5", "6"]

    def test_sbdi_gtdb_puts_the_phylum_one_deeper(self, tmp_path):
        variables = self._introspect(tmp_path, self.SBDI)

        assert variables["PHYLUM_LEVEL"] == "3"
        assert [variables[r] for r in self.RANKS] == ["4", "5", "6", "7"]

    def test_never_deeper_than_the_pipeline_collapsed(self, tmp_path):
        variables = self._introspect(tmp_path, {**self.SBDI, "tax_agglom_max": 2})

        assert variables["PHYLUM_LEVEL"] == "2"

    def test_explicit_value_is_kept_and_the_ranks_follow_it(self, tmp_path):
        variables = self._introspect(tmp_path, self.SBDI, {"PHYLUM_LEVEL": "5"})

        assert variables["PHYLUM_LEVEL"] == "5"
        assert variables["CLASS_LEVEL"] == "6"

    def test_no_params_and_no_outputs_sets_nothing(self, tmp_path):
        variables = self._introspect(tmp_path)

        assert "PHYLUM_LEVEL" not in variables
        assert "CLASS_LEVEL" not in variables

    def test_database_without_a_phylum_rank_sets_nothing(self, tmp_path):
        pr2 = {
            "dada_ref_taxonomy": "pr2",
            "dada_ref_databases": {"pr2": {"taxlevels": "Domain,Supergroup,Division,Class"}},
        }

        assert "PHYLUM_LEVEL" not in self._introspect(tmp_path, pr2)

    def test_placement_taxonomy_ignores_the_dada2_database(self, tmp_path):
        """ampliseq collapses the placement taxonomy, whose ranks params do not name."""
        params = {
            **self.SBDI,
            "skip_dada_taxonomy": True,
            "pplace_tree": "https://example.org/ref.newick",
            "pplace_taxonomy": "https://example.org/ref.taxonomy.tsv",
        }

        assert "PHYLUM_LEVEL" not in self._introspect(tmp_path, params)

    def test_dada2_taxonomy_header_beats_params(self, tmp_path):
        self._write(
            tmp_path / "qiime2" / "rel_abundance_tables" / "rel-table-ASV_with-DADA2-tax.tsv",
            '"ID"\t"Domain"\t"Kingdom"\t"Phylum"\t"Class"\t"sample_1"\n',
        )

        variables = self._introspect(tmp_path, {**self.GTDB, "tax_agglom_max": 6})

        assert variables["PHYLUM_LEVEL"] == "3"

    def test_rank_prefixed_barplot_lineages(self, tmp_path):
        barplot = tmp_path / "qiime2" / "barplot"
        self._write(barplot / "level-1.csv", "index,k__Bacteria,treatment\n")
        self._write(barplot / "level-2.csv", "index,k__Bacteria;p__Firmicutes,treatment\n")

        variables = self._introspect(tmp_path, {**self.SBDI, "multiregion": "regions.tsv"})

        assert variables["PHYLUM_LEVEL"] == "2"


class TestSelectionIsShared:
    def test_helper_orders_newest_first(self, tmp_path):
        """The provenance collector picks matches[-1]; this must name the same file."""
        info = tmp_path / "pipeline_info"
        for name in (
            "params_2026-06-11_16-37-38.json",
            "params_2026-06-11_20-48-02.json",
            "params_2026-06-12_07-20-45.json",
        ):
            _write_params(info, name, {})

        ordered = params_files_newest_first(info)

        assert [p.name for p in ordered] == [
            "params_2026-06-12_07-20-45.json",
            "params_2026-06-11_20-48-02.json",
            "params_2026-06-11_16-37-38.json",
        ]

    def test_patterns_do_not_interleave(self, tmp_path):
        """params*.json wins outright; nf-params.json is not mixed into the order."""
        info = tmp_path / "pipeline_info"
        _write_params(info, "params_2026-01-01_00-00-00.json", {})
        _write_params(info, "nf-params.json", {})

        assert [p.name for p in params_files_newest_first(info)] == [
            "params_2026-01-01_00-00-00.json"
        ]
