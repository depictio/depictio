#def test_list_dashboards(client, mock_user):
def test_list_dashboards(dashboards):
    assert dashboards == ["dashboard_1"]