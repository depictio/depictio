"""Contract for ``GET /advanced_viz/structure/{dc_id}/file``.

The endpoint serves the raw PDB/mmCIF text of a file-backed ``structure`` DC
to the molecule_3d renderer, mirroring the phylogeny/newick endpoint: prefer
the CLI-scanned entry in ``files_collection``, fall back to the project
document's ``scan.scan_parameters.filename`` (reference datasets are seeded,
never CLI-scanned). ``_assert_dc_access`` is the authorisation boundary — a
caller-supplied dc_id must not return raw data without project access, so its
refusal path is tested here alongside the happy paths.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.endpoints.advanced_viz_endpoints import routes

DC_ID = "646b0f3c1e4a2d7f8e5b8d52"

PDB_TEXT = (
    "HEADER    PLANT PROTEIN                           30-APR-81   1CRN\n"
    "ATOM      1  N   THR A   1      17.047  14.099   3.625  1.00 13.79           N\n"
    "END\n"
)


def _collections(file_doc=None, project_doc=None):
    files = MagicMock()
    files.find_one.return_value = file_doc
    projects = MagicMock()
    projects.find_one.return_value = project_doc
    return files, projects


def _project_doc(filename: str) -> dict:
    return {
        "workflows": [
            {
                "data_collections": [
                    {
                        "_id": ObjectId(DC_ID),
                        "config": {"scan": {"scan_parameters": {"filename": filename}}},
                    }
                ]
            }
        ]
    }


def test_serves_file_registered_in_files_collection(tmp_path):
    pdb = tmp_path / "structure.pdb"
    pdb.write_text(PDB_TEXT)
    files, projects = _collections(file_doc={"file_location": str(pdb)})

    with (
        patch.object(routes, "_assert_dc_access"),
        patch("depictio.api.v1.db.files_collection", files),
        patch("depictio.api.v1.db.projects_collection", projects),
    ):
        assert routes.get_structure_file(DC_ID, current_user=MagicMock()) == PDB_TEXT


def test_falls_back_to_project_scan_filename(tmp_path):
    pdb = tmp_path / "structure.pdb"
    pdb.write_text(PDB_TEXT)
    files, projects = _collections(file_doc=None, project_doc=_project_doc(str(pdb)))

    with (
        patch.object(routes, "_assert_dc_access"),
        patch("depictio.api.v1.db.files_collection", files),
        patch("depictio.api.v1.db.projects_collection", projects),
    ):
        assert routes.get_structure_file(DC_ID, current_user=MagicMock()) == PDB_TEXT


def test_404_when_no_location_registered():
    files, projects = _collections()

    with (
        patch.object(routes, "_assert_dc_access"),
        patch("depictio.api.v1.db.files_collection", files),
        patch("depictio.api.v1.db.projects_collection", projects),
    ):
        with pytest.raises(HTTPException) as exc:
            routes.get_structure_file(DC_ID, current_user=MagicMock())
    assert exc.value.status_code == 404


def test_404_when_no_candidate_path_exists(tmp_path):
    files, projects = _collections(
        file_doc={"file_location": str(tmp_path / "gone.pdb")},
        project_doc=_project_doc("/app/does/not/exist.pdb"),
    )

    with (
        patch.object(routes, "_assert_dc_access"),
        patch("depictio.api.v1.db.files_collection", files),
        patch("depictio.api.v1.db.projects_collection", projects),
    ):
        with pytest.raises(HTTPException) as exc:
            routes.get_structure_file(DC_ID, current_user=MagicMock())
    assert exc.value.status_code == 404


def test_access_gate_refusal_propagates_before_any_read(tmp_path):
    pdb = tmp_path / "structure.pdb"
    pdb.write_text(PDB_TEXT)
    files, projects = _collections(file_doc={"file_location": str(pdb)})

    with (
        patch.object(
            routes,
            "_assert_dc_access",
            side_effect=HTTPException(status_code=404, detail="Data collection not found"),
        ),
        patch("depictio.api.v1.db.files_collection", files),
        patch("depictio.api.v1.db.projects_collection", projects),
    ):
        with pytest.raises(HTTPException) as exc:
            routes.get_structure_file(DC_ID, current_user=MagicMock())
    assert exc.value.status_code == 404
    files.find_one.assert_not_called()
