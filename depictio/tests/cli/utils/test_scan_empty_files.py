"""Empty files are skipped by the scan instead of failing it.

Pipelines write zero-byte placeholders (nf-core/proteinfold writes empty ipTM files
for monomer targets); `File` refuses a zero size, so the scan must drop them.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from depictio.cli.cli.utils.scan import scan_single_file


def _scan(path):
    return scan_single_file(
        file_location=str(path),
        run=MagicMock(),
        data_collection=MagicMock(),
        permissions=MagicMock(),
        existing_files={},
        update_files=False,
        skip_regex=True,
    )


def test_empty_file_is_skipped(tmp_path):
    empty = tmp_path / "T1_iptm.tsv"
    empty.touch()
    assert _scan(empty) is None
