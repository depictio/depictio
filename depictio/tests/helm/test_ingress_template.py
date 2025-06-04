from pathlib import Path


def test_ingress_template_service_names():
    template = Path("helm-charts/depictio/templates/ingress.yaml").read_text()
    assert "{{ .Release.Name }}-api" in template
    assert "{{ .Release.Name }}-minio" in template
    assert "/minio" in template

