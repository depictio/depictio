import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main
from fastapi.testclient import TestClient


def test_create_multiqc_file():
    client = TestClient(main.app)
    response = client.post(
        "/multiqc_files/workflow_name", json={"file_path": "file_path", "run_name": "run_name", "wf_name": "workflow_name"}
    )
    assert response.status_code == 200
    assert response.json() == {"inserted_id": "some_id"}


def test_get_multiqc_files():
    client = TestClient(main.app)
    response = client.get("/multiqc_files/workflow_name")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["file_path"] == "file_path"
    assert response.json()[0]["run_name"] == "run_name"
    assert response.json()[0]["wf_name"] == "workflow_name"


def test_get_workflows():
    client = TestClient(main.app)
    response = client.get("/workflows")
    print(response.json())
    assert response.status_code == 200
    assert response.json() == ["workflow_name"]


def test_get_runs():
    client = TestClient(main.app)
    response = client.get("/runs/workflow_name")
    assert response.status_code == 200
    assert response.json() == {"workflow_name": ["run_name"]}
