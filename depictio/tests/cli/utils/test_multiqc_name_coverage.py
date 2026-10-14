"""Offline unit tests for the pure ``coverage`` core of scripts/multiqc_name_coverage.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "multiqc_name_coverage.py"


@pytest.fixture(scope="module")
def mnc() -> ModuleType:
    spec = importlib.util.spec_from_file_location("multiqc_name_coverage", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exact_names_attach(mnc: ModuleType) -> None:
    cov = mnc.coverage(["A", "B"], ["A", "B"])
    assert cov["attached"] == 2
    assert cov["total"] == 2
    assert cov["unattached"] == []
    assert cov["by_hub"] == {"A": ["A"], "B": ["B"]}


def test_read_suffix_variants_attach(mnc: ModuleType) -> None:
    names = ["NA12878", "NA12878_1", "NA12878_2", "NA12878_val_1"]
    cov = mnc.coverage(["NA12878"], names)
    assert cov["attached"] == cov["total"] == 4
    assert sorted(cov["by_hub"]["NA12878"]) == sorted(names)


def test_prefix_at_token_boundary_attaches(mnc: ModuleType) -> None:
    cov = mnc.coverage(["NA12878"], ["NA12878_75M.md"])
    assert cov["by_hub"] == {"NA12878": ["NA12878_75M.md"]}
    assert cov["unattached"] == []


def test_prefix_inside_a_token_does_not_attach(mnc: ModuleType) -> None:
    cov = mnc.coverage(["NA12"], ["NA12878"])
    assert cov["attached"] == 0
    assert cov["unattached"] == ["NA12878"]


def test_nested_ids_longest_hub_wins(mnc: ModuleType) -> None:
    cov = mnc.coverage(["S1", "S1_2"], ["S1_2.md", "S1_3.md"])
    assert cov["by_hub"]["S1_2"] == ["S1_2.md"]
    assert cov["by_hub"]["S1"] == ["S1_3.md"]


def test_hub_claiming_nothing_and_unattached_names(mnc: ModuleType) -> None:
    cov = mnc.coverage(["A", "Z"], ["A", "A_1", "NanoStats"])
    assert cov["by_hub"]["Z"] == []
    assert cov["unattached"] == ["NanoStats"]
    assert (cov["attached"], cov["total"]) == (2, 3)


def test_names_are_deduplicated_and_blanks_ignored(mnc: ModuleType) -> None:
    cov = mnc.coverage(["A", ""], ["A", "A", "", None])
    assert cov["total"] == 1
    assert list(cov["by_hub"]) == ["A"]


def test_mapping_names_unions_keys_and_variants(mnc: ModuleType) -> None:
    assert mnc.mapping_names({"A": ["A_1", "A_2"], "B": []}) == ["A", "A_1", "A_2", "B"]


def test_infix_sample_id_attaches_to_its_hub(mnc: ModuleType) -> None:
    """mag-style names carry the hub id after an assembler/binner prefix."""
    names = ["FLYE-CAPES_S11", "FLYE-MaxBin2-CAPES_S11.001"]
    cov = mnc.coverage(["CAPES_S11", "CAPES_S12"], names)
    assert cov["attached"] == 2
    assert cov["unattached"] == []
    assert cov["by_hub"]["CAPES_S11"] == sorted(names)
    assert cov["by_hub"]["CAPES_S12"] == []
