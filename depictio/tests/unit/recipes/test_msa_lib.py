"""Shared MSA helpers: parsers and the canonical MSA table."""

from __future__ import annotations

import polars as pl
import pytest

from depictio.recipes.lib.msa import (
    AF_RESTYPE_ALPHABET,
    HHBLITS_ALPHABET,
    MSA_SCHEMA,
    best_alphabet,
    decode_hhblits_rows,
    msa_frame,
    parse_a3m,
    parse_fasta_alignment,
    parse_stockholm,
)


def test_decode_hhblits_rows_reads_codes_and_text_lines() -> None:
    # M V S N W, then a gap and an unknown residue
    assert decode_hhblits_rows([[10, 17, 15, 11, 18], "10\t21\t20"]) == ["MVSNW", "M-X"]


def test_decode_hhblits_rows_skips_blank_rows_and_rejects_bad_codes() -> None:
    assert decode_hhblits_rows(["", [], "0 1"]) == ["AC"]
    with pytest.raises(ValueError):
        decode_hhblits_rows([[len(HHBLITS_ALPHABET)]])


def test_best_alphabet_tells_multimer_order_from_monomer_order() -> None:
    query = "AKNSLTTK"
    monomer = [str(HHBLITS_ALPHABET.index(c)) for c in query]
    multimer = [str(AF_RESTYPE_ALPHABET.index(c)) for c in query]
    assert best_alphabet([" ".join(monomer)], query) == HHBLITS_ALPHABET
    assert best_alphabet(["", multimer], "AKNS:LTTK") == AF_RESTYPE_ALPHABET
    assert decode_hhblits_rows([multimer], AF_RESTYPE_ALPHABET) == [query]
    assert best_alphabet([multimer], "") == HHBLITS_ALPHABET


def test_parse_a3m_drops_lowercase_insertions() -> None:
    text = ">query desc\nMKV\nLA\n>hit1\nMkkV-A\n>hit2\nM.VLa\n"
    assert parse_a3m(text) == [("query", "MKVLA"), ("hit1", "MV-A"), ("hit2", "M-VL")]


def test_parse_stockholm_interleaved_hmmer_drops_inserts() -> None:
    text = (
        "# STOCKHOLM 1.0\n#=GF ID fam\n"
        "seqA  MK.V\nseqB  MKaV\n\n"
        "seqA  LL\nseqB  L-\n#=GC RF xx.xxx\n//\n"
    )
    assert parse_stockholm(text) == [("seqA", "MKVLL"), ("seqB", "MKVL-")]


def test_parse_stockholm_keeps_dot_gaps_without_inserts() -> None:
    text = "# STOCKHOLM 1.0\nseqA MK.V\nseqB MKLV\n//\n"
    assert parse_stockholm(text) == [("seqA", "MK-V"), ("seqB", "MKLV")]


def test_parse_fasta_alignment_multiline() -> None:
    text = ">a\nMK-\nV\n>b\nM.LV\n"
    assert parse_fasta_alignment(text) == [("a", "MK-V"), ("b", "M-LV")]


def test_msa_frame_identity_coverage_and_rank() -> None:
    records = [("q", "MKV-L"), ("h", "MRV-L"), ("h", "--VAL"), ("gap", "-----")]
    df = msa_frame(records, "P1")
    assert df.schema == pl.Schema(MSA_SCHEMA)
    assert df["rank"].to_list() == [0, 1, 2, 3]
    assert df["seq_id"].to_list() == ["q", "h", "h_2", "gap"]
    assert df["msa_id"].unique().to_list() == ["P1"]
    assert df["identity"].to_list() == [1.0, 0.75, 1.0, 0.0]
    assert df["coverage"].to_list() == [1.0, 1.0, 0.5, 0.0]


def test_msa_frame_caps_in_rank_order() -> None:
    records = [(f"s{i}", "MK") for i in range(10)]
    df = msa_frame(records, "P1", cap=3)
    assert df["seq_id"].to_list() == ["s0", "s1", "s2"]


def test_msa_frame_rejects_ragged_rows_and_handles_empty() -> None:
    with pytest.raises(ValueError):
        msa_frame([("a", "MKV"), ("b", "MK")], "P1")
    empty = msa_frame([], "P1")
    assert empty.height == 0
    assert empty.schema == pl.Schema(MSA_SCHEMA)
