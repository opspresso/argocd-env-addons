from pathlib import Path
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("platform", ["eks", "k3s"])
def test_argocd_monitoring_matches_the_platform_collector(platform):
    chart = ROOT / "charts/argo-cd"
    result = subprocess.run([
        "helm", "template", "argocd", str(chart),
        "-f", str(chart / "values.yaml"), "-f", str(chart / f"{platform}/values-{platform}-demo.yaml"),
        "--api-versions", "monitoring.coreos.com/v1",
    ], capture_output=True, text=True, check=True)
    documents = [item for item in yaml.safe_load_all(result.stdout) if item]
    monitors = [item for item in documents if item["kind"] == "ServiceMonitor"]
    if platform == "eks":
        assert monitors
        assert all(item["metadata"]["labels"]["release"] == "prometheus-eks-demo" for item in monitors)
    else:
        assert not any(item["kind"] in {"ServiceMonitor", "PodMonitor", "Prometheus", "VMSingle"} for item in documents)
    assert any(item["kind"] == "Deployment" and item["metadata"]["name"] == "argocd-server" for item in documents)
