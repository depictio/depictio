"""PAE matrices from nf-core/proteinfold TSVs, AlphaFold DB and ColabFold JSON."""

from __future__ import annotations

import gzip
import json

import pytest

from depictio.recipes.lib.pae import max_pae, read_pae, write_pae_tsv

MATRIX = [
    [0.0, 1.5, 4.25],
    [2.0, 0.0, 10.5],
    [3.75, 12.0, 0.0],
]


def test_tab_separated():
    text = "0.0\t1.5\t4.25\n2.0\t0.0\t10.5\n3.75\t12.0\t0.0\n"
    assert read_pae(text) == MATRIX


def test_whitespace_separated_with_blank_lines_and_crlf():
    text = "\n 0.0   1.5  4.25 \r\n\r\n2.0 0.0 10.5\r\n3.75\t12.0  0.0\n\n"
    assert read_pae(text) == MATRIX


def test_comma_separated_and_bytes():
    text = "0.0,1.5,4.25\n2.0,0.0,10.5\n3.75,12.0,0.0\n"
    assert read_pae(text) == MATRIX
    assert read_pae(text.encode()) == MATRIX
    assert read_pae(b"\xef\xbb\xbf" + text.encode()) == MATRIX  # BOM


def test_header_row_of_names_is_skipped():
    assert read_pae("r1,r2,r3\n0.0,1.5,4.25\n2.0,0.0,10.5\n3.75,12.0,0.0\n") == MATRIX
    assert read_pae("A B C\n0 1.5 4.25\n2 0 10.5\n3.75 12 0\n") == MATRIX


def test_integers_and_scientific_notation():
    assert read_pae("0 1\n1e0 0\n") == [[0.0, 1.0], [1.0, 0.0]]


def test_gzip_bytes_of_text_and_of_json():
    tsv = write_pae_tsv(MATRIX)
    assert read_pae(gzip.compress(tsv.encode())) == MATRIX
    payload = json.dumps([{"predicted_aligned_error": MATRIX}])
    assert read_pae(gzip.compress(payload.encode())) == MATRIX


def test_alphafold_db_v4_json():
    payload = [
        {
            "predicted_aligned_error": [[0, 1.5, 4.25], [2, 0, 10.5], [3.75, 12, 0]],
            "max_predicted_aligned_error": 31.75,
        }
    ]
    assert read_pae(json.dumps(payload)) == MATRIX
    assert read_pae(json.dumps(payload).encode()) == MATRIX
    assert all(isinstance(v, float) for row in read_pae(json.dumps(payload)) for v in row)


def test_colabfold_json_objects():
    assert read_pae(json.dumps({"predicted_aligned_error": MATRIX})) == MATRIX
    assert (
        read_pae(json.dumps({"pae": MATRIX, "plddt": [90.0, 80.0, 70.0], "max_pae": 31.75}))
        == MATRIX
    )


def test_alphafold_db_v1_flattened_pairs():
    residue1 = [i for i in (1, 2, 3) for _ in range(3)]
    residue2 = [j for _ in range(3) for j in (1, 2, 3)]
    distance = [v for row in MATRIX for v in row]
    payload = [
        {
            "residue1": residue1,
            "residue2": residue2,
            "distance": distance,
            "max_predicted_aligned_error": 31.75,
        }
    ]
    assert read_pae(json.dumps(payload)) == MATRIX
    # the pair order does not matter
    shuffled = list(zip(residue1, residue2, distance))[::-1]
    reordered = [
        {
            "residue1": [a for a, _, _ in shuffled],
            "residue2": [b for _, b, _ in shuffled],
            "distance": [c for _, _, c in shuffled],
        }
    ]
    assert read_pae(json.dumps(reordered)) == MATRIX


def test_alphafold_db_v1_with_missing_pairs_raises():
    payload = [{"residue1": [1, 1, 2], "residue2": [1, 2, 1], "distance": [0.0, 1.0, 1.0]}]
    with pytest.raises(ValueError, match="full 2 x 2"):
        read_pae(json.dumps(payload))
    with pytest.raises(ValueError, match="differ in length"):
        read_pae(json.dumps([{"residue1": [1], "residue2": [1, 2], "distance": [0.0]}]))
    with pytest.raises(ValueError, match="1-based"):
        read_pae(json.dumps([{"residue1": [0], "residue2": [1], "distance": [0.0]}]))


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ("1 2 3\n4 5 6\n", "square"),
        ("1 2\n3 4\n5 6\n", "square"),
        ("1 2 3\n4 5\n6 7 8\n", "square"),
        (json.dumps({"predicted_aligned_error": [[1, 2, 3], [4, 5, 6]]}), "square"),
        (json.dumps([{"predicted_aligned_error": [[1, 2], [3]]}]), "square"),
        ("", "empty"),
        ("   \n\n", "empty"),
        ("0 1\n1 x\n", "non-numeric"),
        ("{not json", "not valid"),
        (json.dumps({"something": 1}), "none of"),
        (json.dumps({"pae": [[1, "a"], [2, 3]]}), "non-numeric"),
        (json.dumps({"pae": [1, 2]}), "list of rows"),
        (json.dumps({"pae": []}), "no PAE rows"),
        ("[7]", "list of rows"),
        ("null", "no PAE rows"),
    ],
)
def test_invalid_input_raises_value_error(data, message):
    with pytest.raises(ValueError, match=message):
        read_pae(data)


def test_max_pae():
    assert max_pae(MATRIX) == 12.0
    assert max_pae([[3.0]]) == 3.0
    with pytest.raises(ValueError, match="empty"):
        max_pae([])


def test_write_pae_tsv_layout():
    text = write_pae_tsv(MATRIX)
    assert text == "0.00\t1.50\t4.25\n2.00\t0.00\t10.50\n3.75\t12.00\t0.00\n"
    assert text.endswith("\n") and not text.endswith("\n\n")
    assert write_pae_tsv([[0.0, 1.256], [7.0, 0.0]], decimals=1) == "0.0\t1.3\n7.0\t0.0\n"
    assert write_pae_tsv([[1.4, 2.6]], decimals=0) == "1\t3\n"
    assert write_pae_tsv([]) == ""


def test_write_then_read_round_trips():
    assert read_pae(write_pae_tsv(MATRIX)) == MATRIX
    big = [[round((i * 7 + j * 3) % 31.75, 2) for j in range(40)] for i in range(40)]
    assert read_pae(write_pae_tsv(big)) == big
    assert max_pae(read_pae(write_pae_tsv(big))) == max_pae(big)
