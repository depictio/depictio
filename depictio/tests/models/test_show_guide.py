"""``show_guide`` / ``guide_intro``: the built-in Guide page and its author note."""

from depictio.models.models.dashboards import DashboardDataLite


def test_guide_defaults_on_with_no_intro_and_stays_out_of_yaml():
    dash = DashboardDataLite(title="T", components=[])
    assert dash.show_guide is True
    assert dash.guide_intro == ""
    yaml_str = dash.to_yaml()
    assert "show_guide" not in yaml_str
    assert "guide_intro" not in yaml_str


def test_guide_off_and_intro_survive_yaml_and_full_round_trips():
    dash = DashboardDataLite(
        title="T",
        components=[],
        show_guide=False,
        guide_intro="Start with the **Overview** tab.",
    )
    yaml_str = dash.to_yaml()
    assert "show_guide: false" in yaml_str
    assert "guide_intro:" in yaml_str
    back = DashboardDataLite.from_yaml(yaml_str)
    assert back.show_guide is False
    assert back.guide_intro == "Start with the **Overview** tab."
    full = dash.to_full()
    assert full["show_guide"] is False
    assert full["guide_intro"] == "Start with the **Overview** tab."
    again = DashboardDataLite.from_full(full)
    assert again.show_guide is False
    assert again.guide_intro == "Start with the **Overview** tab."


def test_pre_feature_document_reads_as_guide_on():
    full = DashboardDataLite(title="T", components=[]).to_full()
    full.pop("show_guide")
    full.pop("guide_intro")
    back = DashboardDataLite.from_full(full)
    assert back.show_guide is True
    assert back.guide_intro == ""
