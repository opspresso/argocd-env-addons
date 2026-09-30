from pathlib import Path
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("chart,platform,cluster,release,namespace,route_names", [
    ("grafana", "eks", "eks-demo", "grafana", "addon-grafana", {"grafana"}),
    ("grafana", "k3s", "k3s-demo", "grafana", "addon-grafana", {"grafana"}),
    ("prometheus-stack", "eks", "eks-demo", "prometheus-eks-demo", "addon-prometheus", {"prometheus-prometheus"}),
    ("argo-rollouts", "eks", "eks-demo", "argo-rollouts", "addon-argo-rollouts", {"argo-rollouts-dashboard"}),
    ("argo-workflows", "eks", "eks-demo", "argo-workflows", "addon-argo-workflows", {"argo-workflows-server"}),
    ("atlantis", "eks", "eks-demo", "atlantis", "addon-atlantis", {"atlantis", "atlantis-public"}),
])
def test_native_routes_target_the_rendered_service_ports(chart, platform, cluster, release, namespace, route_names):
    path = ROOT / "charts" / chart
    result = subprocess.run(
        ["helm", "template", release, str(path), "--namespace", namespace,
         "-f", str(path / "values.yaml"), "-f", str(path / platform / f"values-{cluster}.yaml")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    docs = [doc for doc in yaml.safe_load_all(result.stdout) if doc]
    services = {doc["metadata"]["name"]: doc for doc in docs if doc["kind"] == "Service"}
    routes = [doc for doc in docs if doc["kind"] == "HTTPRoute"]
    assert {route["metadata"]["name"] for route in routes} == route_names
    for route in routes:
        assert route["metadata"]["namespace"] == namespace
        assert route["spec"]["hostnames"]
        assert route["spec"]["parentRefs"]
        for rule in route["spec"]["rules"]:
            for backend in rule["backendRefs"]:
                service = services[backend["name"]]
                assert backend["port"] in {port["port"] for port in service["spec"]["ports"]}
        if route["metadata"]["name"] == "atlantis-public":
            assert route["spec"]["rules"][0]["matches"] == [{"path": {"type": "PathPrefix", "value": "/events"}}]
