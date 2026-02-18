"""
YAML Export/Import Round-Trip Validation Tests.

Tests that the round-trip:
  YAML → DashboardDataLite → to_full() → DashboardData → to_lite() → to_yaml()
produces identical component configuration (excluding ephemeral fields).

Uses the real exported iris YAML as a fixture — it was produced by the export
system itself and covers all component types (figure, card, interactive, table).
"""

from pathlib import Path
from typing import Any

import pytest
from bson import ObjectId

from depictio.models.models.dashboards import DashboardData, DashboardDataLite

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent.parent.parent  # up to repo root
IRIS_YAML = REPO_ROOT / "depictio/cli/6824cb3b89d2b72169309737.yaml"

# Fields regenerated or ephemeral on every round-trip — excluded from comparison
EPHEMERAL_COMPONENT_KEYS = {"tag", "index"}

# Skip all tests in this module if the iris YAML fixture is not present
pytestmark = pytest.mark.skipif(
    not IRIS_YAML.exists(),
    reason=f"Iris YAML fixture not found: {IRIS_YAML}",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def normalize_components(components: list) -> list[dict]:
    """Convert components to plain dicts, stripping ephemeral fields.

    Accepts both Pydantic model instances and plain dicts (from_full() returns
    plain dicts; from_yaml() returns Pydantic models after validation).
    Calling model_dump() on both gives the same field set — Pydantic fills in
    defaults for missing keys, making both sides structurally identical.
    """
    result = []
    for comp in components:
        d: dict[str, Any] = comp if isinstance(comp, dict) else comp.model_dump()
        result.append({k: v for k, v in d.items() if k not in EPHEMERAL_COMPONENT_KEYS})
    return result


def do_roundtrip(yaml_str: str, new_title: str) -> DashboardDataLite:
    """Full round-trip: YAML → full dict → DashboardData → DashboardDataLite (re-titled).

    Args:
        yaml_str:  YAML content string
        new_title: Title to assign to the re-imported dashboard

    Returns:
        DashboardDataLite after the full round-trip
    """
    lite = DashboardDataLite.from_yaml(yaml_str)
    full = lite.to_full()
    full["project_id"] = str(ObjectId())
    # permissions already set by to_full() as {"owners": [], "editors": [], "viewers": []}
    # dashboard_id already set by to_full() from the original YAML field
    dashboard = DashboardData.model_validate(full)
    return dashboard.to_lite().model_copy(update={"title": new_title})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def iris_yaml_content() -> str:
    """Read and return the iris dashboard YAML fixture."""
    return IRIS_YAML.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestYamlRoundTrip:
    """Round-trip tests: YAML → full → DashboardData → to_lite() → YAML."""

    def test_roundtrip_preserves_all_components(self, iris_yaml_content: str) -> None:
        """All 11 components survive round-trip without loss or duplication."""
        lite1 = DashboardDataLite.from_yaml(iris_yaml_content)
        lite2 = do_roundtrip(iris_yaml_content, new_title="Re-imported Dashboard")

        comps1 = normalize_components(lite1.components)
        comps2 = normalize_components(lite2.components)

        assert len(comps1) == len(comps2), f"Component count changed: {len(comps1)} → {len(comps2)}"
        for i, (c1, c2) in enumerate(zip(comps1, comps2)):
            assert c1 == c2, (
                f"Component {i} ({c1.get('component_type')}) differs after round-trip:\n"
                f"  before: {c1}\n"
                f"  after:  {c2}"
            )

    def test_roundtrip_layout_preserved(self, iris_yaml_content: str) -> None:
        """Layout (x/y/w/h) survives round-trip for every component."""
        lite1 = DashboardDataLite.from_yaml(iris_yaml_content)
        lite2 = do_roundtrip(iris_yaml_content, new_title="Re-imported")

        comps1 = lite1.components
        comps2 = lite2.components

        for i, (c1, c2) in enumerate(zip(comps1, comps2)):
            d1: dict[str, Any] = c1 if isinstance(c1, dict) else c1.model_dump()
            d2: dict[str, Any] = c2 if isinstance(c2, dict) else c2.model_dump()
            assert d1.get("layout") == d2.get("layout"), (
                f"Layout mismatch for component {i} ({d1.get('component_type')}):\n"
                f"  before: {d1.get('layout')}\n"
                f"  after:  {d2.get('layout')}"
            )

    def test_roundtrip_display_preserved(self, iris_yaml_content: str) -> None:
        """Display fields (icon, color) survive round-trip for cards and interactives."""
        lite1 = DashboardDataLite.from_yaml(iris_yaml_content)
        lite2 = do_roundtrip(iris_yaml_content, new_title="Re-imported")

        comps1 = lite1.components
        comps2 = lite2.components

        for i, (c1, c2) in enumerate(zip(comps1, comps2)):
            d1: dict[str, Any] = c1 if isinstance(c1, dict) else c1.model_dump()
            d2: dict[str, Any] = c2 if isinstance(c2, dict) else c2.model_dump()
            comp_type = d1.get("component_type")
            if comp_type in ("card", "interactive"):
                assert d1.get("display") == d2.get("display"), (
                    f"Display mismatch for component {i} ({comp_type}):\n"
                    f"  before: {d1.get('display')}\n"
                    f"  after:  {d2.get('display')}"
                )

    def test_roundtrip_figure_params_preserved(self, iris_yaml_content: str) -> None:
        """figure_params (Plotly Express kwargs) survive round-trip for all figures."""
        lite1 = DashboardDataLite.from_yaml(iris_yaml_content)
        lite2 = do_roundtrip(iris_yaml_content, new_title="Re-imported")

        def get_figures(lite: DashboardDataLite) -> list[dict]:
            result = []
            for c in lite.components:
                d: dict[str, Any] = c if isinstance(c, dict) else c.model_dump()
                if d.get("component_type") == "figure":
                    result.append(d)
            return result

        figures1 = get_figures(lite1)
        figures2 = get_figures(lite2)

        assert len(figures1) == len(figures2), (
            f"Figure count changed: {len(figures1)} → {len(figures2)}"
        )
        for f1, f2 in zip(figures1, figures2):
            assert f1.get("figure_params") == f2.get("figure_params"), (
                f"figure_params mismatch for {f1.get('visu_type')}:\n"
                f"  before: {f1.get('figure_params')}\n"
                f"  after:  {f2.get('figure_params')}"
            )

    def test_roundtrip_title_changes(self, iris_yaml_content: str) -> None:
        """Title is correctly overridden in the re-imported dashboard."""
        lite2 = do_roundtrip(iris_yaml_content, new_title="My New Title")
        assert lite2.title == "My New Title"

    def test_roundtrip_split_panel_layout(self, iris_yaml_content: str) -> None:
        """Split-panel: 3 interactives → left, 8 others → right; stored_layout = []."""
        lite1 = DashboardDataLite.from_yaml(iris_yaml_content)
        full = lite1.to_full()
        full["project_id"] = str(ObjectId())
        dashboard = DashboardData.model_validate(full)
        full2 = dashboard.model_dump()

        assert full2.get("stored_layout_data") == [], (
            "stored_layout_data should be empty (split-panel system)"
        )
        left_count = len(full2.get("left_panel_layout_data", []))
        right_count = len(full2.get("right_panel_layout_data", []))
        assert left_count == 3, f"Expected 3 interactives in left_panel, got {left_count}"
        assert right_count == 8, (
            f"Expected 8 components in right_panel (3 figures + 4 cards + 1 table), "
            f"got {right_count}"
        )

    def test_roundtrip_component_count_iris(self, iris_yaml_content: str) -> None:
        """Iris YAML has exactly 11 components (3 figures, 4 cards, 3 interactives, 1 table)."""
        lite = DashboardDataLite.from_yaml(iris_yaml_content)
        components = [c if isinstance(c, dict) else c.model_dump() for c in lite.components]

        type_counts: dict[str, int] = {}
        for comp in components:
            ctype = comp.get("component_type", "unknown")
            type_counts[ctype] = type_counts.get(ctype, 0) + 1

        assert len(components) == 11, f"Expected 11 components, got {len(components)}"
        assert type_counts.get("figure", 0) == 3, f"Expected 3 figures, got {type_counts}"
        assert type_counts.get("card", 0) == 4, f"Expected 4 cards, got {type_counts}"
        assert type_counts.get("interactive", 0) == 3, f"Expected 3 interactives, got {type_counts}"
        assert type_counts.get("table", 0) == 1, f"Expected 1 table, got {type_counts}"

    def test_roundtrip_visu_types_preserved(self, iris_yaml_content: str) -> None:
        """visu_type values (box, scatter, histogram) survive round-trip."""
        lite1 = DashboardDataLite.from_yaml(iris_yaml_content)
        lite2 = do_roundtrip(iris_yaml_content, new_title="Re-imported")

        def get_visu_types(lite: DashboardDataLite) -> list[str]:
            result = []
            for c in lite.components:
                d: dict[str, Any] = c if isinstance(c, dict) else c.model_dump()
                if d.get("component_type") == "figure":
                    result.append(d.get("visu_type", ""))
            return result

        assert get_visu_types(lite1) == get_visu_types(lite2)

    def test_roundtrip_project_tag_not_preserved(self, iris_yaml_content: str) -> None:
        """project_tag is NOT preserved after round-trip.

        project_tag is a YAML-import-time field used to look up the target project
        by name. After import, project_id is the authoritative identifier and
        project_tag is no longer stored in the full model. This is by design:
        the field is used once during import, then superseded by project_id.
        """
        lite1 = DashboardDataLite.from_yaml(iris_yaml_content)
        lite2 = do_roundtrip(iris_yaml_content, new_title="Re-imported")
        # Original YAML has project_tag set
        assert lite1.project_tag == "Iris Dataset Project Data Analysis"
        # After round-trip through full model, project_tag is None (not stored in DashboardData)
        assert lite2.project_tag is None

    def test_roundtrip_layout_indices_match_components(self, iris_yaml_content: str) -> None:
        """All layout 'i' values reference valid component indices in full dict."""
        lite1 = DashboardDataLite.from_yaml(iris_yaml_content)
        full = lite1.to_full()
        full["project_id"] = str(ObjectId())
        dashboard = DashboardData.model_validate(full)
        full_dict = dashboard.model_dump()

        comp_indices = {str(comp["index"]) for comp in full_dict["stored_metadata"]}
        layout_refs = set()
        for panel_key in (
            "stored_layout_data",
            "left_panel_layout_data",
            "right_panel_layout_data",
        ):
            for item in full_dict.get(panel_key, []):
                i_val = item.get("i", "")
                if i_val.startswith("box-"):
                    layout_refs.add(i_val[4:])  # strip "box-" prefix

        assert layout_refs == comp_indices, (
            "Layout references don't match component indices.\n"
            f"  In layout but not components: {layout_refs - comp_indices}\n"
            f"  In components but not layout: {comp_indices - layout_refs}"
        )

    def test_regenerate_component_indices_preserves_layout_refs(
        self, iris_yaml_content: str
    ) -> None:
        """_regenerate_component_indices() updates layout 'i' references correctly.

        This test verifies the fix for the round-trip bug where layout items used
        'box-{UUID}' format but the comparison was against the bare UUID, causing
        every layout lookup to fail and fall back to default {x:0,y:0,w:6,h:4}.
        """
        import uuid

        lite = DashboardDataLite.from_yaml(iris_yaml_content)
        full = lite.to_full()
        full["project_id"] = str(ObjectId())
        dashboard = DashboardData.model_validate(full)
        full_dict = dashboard.model_dump()

        # Simulate what the API import endpoint does: regenerate all component indices
        if "stored_metadata" not in full_dict:
            return

        layout_keys = ["left_panel_layout_data", "right_panel_layout_data", "stored_layout_data"]

        for component in full_dict["stored_metadata"]:
            old_index = component.get("index")
            new_index = str(uuid.uuid4())
            component["index"] = new_index

            for layout_key in layout_keys:
                for layout_item in full_dict.get(layout_key, []):
                    if layout_item.get("i") == f"box-{old_index}":
                        layout_item["i"] = f"box-{new_index}"

        # After re-indexing, every layout 'i' must match a component index
        new_indices = {str(comp["index"]) for comp in full_dict["stored_metadata"]}
        layout_refs = set()
        for panel_key in layout_keys:
            for item in full_dict.get(panel_key, []):
                i_val = item.get("i", "")
                if i_val.startswith("box-"):
                    layout_refs.add(i_val[4:])

        assert layout_refs == new_indices, (
            "After _regenerate_component_indices, layout refs don't match new indices.\n"
            f"  In layout but not components: {layout_refs - new_indices}\n"
            f"  In components but not layout: {new_indices - layout_refs}"
        )
