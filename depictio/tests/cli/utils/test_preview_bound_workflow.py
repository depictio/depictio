"""A bind that moves a workflow's walk does not move its single-file collections."""

from depictio.cli.cli.utils.data_root import LocalDataRoot
from depictio.cli.cli.utils.template_preview import preview_data_collections


def _config(root, walked) -> dict:
    return {
        "workflows": [
            {
                "data_location": {"structure": "flat", "locations": [str(walked)]},
                "data_collections": [
                    {
                        "data_collection_tag": "sheet",
                        "config": {
                            "scan": {
                                "mode": "single",
                                "scan_parameters": {"filename": str(root / "input" / "sheet.csv")},
                            }
                        },
                    }
                ],
            }
        ]
    }


def test_a_single_file_gone_is_missing_whether_or_not_the_walk_moved(tmp_path):
    root = tmp_path / "run"
    (root / "bound").mkdir(parents=True)
    data_root = LocalDataRoot(str(root))

    for walked in (root, root / "bound"):
        rows, _runs = preview_data_collections(_config(root, walked), data_root)
        assert [(r.tag, r.status, r.matched) for r in rows] == [("sheet", "missing", 0)]


def test_a_single_file_present_is_counted_after_the_walk_moved(tmp_path):
    root = tmp_path / "run"
    (root / "bound").mkdir(parents=True)
    (root / "input").mkdir()
    (root / "input" / "sheet.csv").write_text("sample\n")

    rows, _runs = preview_data_collections(_config(root, root / "bound"), LocalDataRoot(str(root)))
    assert [(r.tag, r.status, r.matched) for r in rows] == [("sheet", "ok", 1)]
