"""Validate deployed alert expressions with synthetic healthy/failure time series."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PROMETHEUS_IMAGE = "quay.io/prometheus/prometheus:v3.14.0-distroless"


@pytest.fixture(scope="module")
def rendered_grafana():
    chart = ROOT / "charts/grafana"
    result = subprocess.run(
        ["helm", "template", "grafana", str(chart), "-f", str(chart / "values.yaml"),
         "-f", str(chart / "eks/values-eks-demo.yaml")], capture_output=True, text=True, check=True,
    )
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def test_node_alerts_evaluate_the_rendered_queries(rendered_grafana, tmp_path):
    secret = next(doc for doc in rendered_grafana if "node-health.yaml" in (doc.get("stringData") or {}))
    provisioned = yaml.safe_load(secret["stringData"]["node-health.yaml"])
    rules = []
    for rule in provisioned["groups"][0]["rules"]:
        query, condition = rule["data"]
        evaluator = condition["model"]["conditions"][0]["evaluator"]
        operator = {"gt": ">", "lt": "<"}[evaluator["type"]]
        rules.append({"alert": rule["uid"], "expr": f'({query["model"]["expr"]}) {operator} {evaluator["params"][0]}', "for": rule["for"]})
    (tmp_path / "rules.yaml").write_text(yaml.safe_dump({"groups": [{"name": "node-health", "interval": "30s", "rules": rules}]}))
    shutil.copy(ROOT / "tests/node-health-alerts.test.yaml", tmp_path / "tests.yaml")
    if shutil.which("promtool"):
        command = ["promtool"]
    elif shutil.which("docker") and subprocess.run(
        ["docker", "image", "inspect", PROMETHEUS_IMAGE], capture_output=True,
    ).returncode == 0:
        command = ["docker", "run", "--rm", "--pull=never", "-v", f"{tmp_path}:/work", "-w", "/work",
                   "--entrypoint=/bin/promtool", PROMETHEUS_IMAGE]
    else:
        pytest.skip("promtool or the pinned local Prometheus image is required; no implicit download")
    result = subprocess.run(command + ["test", "rules", "tests.yaml"], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_dashboard_change_updates_the_pod_template(tmp_path):
    """A JSON-only GitOps change must restart the URL downloader."""
    chart = tmp_path / "charts/grafana"
    shutil.copytree(ROOT / "charts/grafana", chart, ignore=shutil.ignore_patterns("charts"))
    shutil.copytree(ROOT / "env", tmp_path / "env")
    # The generator resolves its policy file relative to its own script.
    import gen_values
    previous = Path.cwd()
    try:
        os.chdir(tmp_path)
        args = type("Args", (), {"reponame": "grafana", "platform": "eks"})()
        gen_values.gen_repos(args, "yaml.j2")
        first = yaml.safe_load((chart / "eks/values-eks-demo.yaml").read_text())
        dashboard = chart / "dashboards/kube-cluster.json"
        data = json.loads(dashboard.read_text())
        data["description"] += " Updated host-health explanation."
        dashboard.write_text(json.dumps(data))
        gen_values.gen_repos(args, "yaml.j2")
        second = yaml.safe_load((chart / "eks/values-eks-demo.yaml").read_text())
    finally:
        os.chdir(previous)
    assert first["grafana"]["podAnnotations"]["checksum/managed-dashboards"] != second["grafana"]["podAnnotations"]["checksum/managed-dashboards"]


def test_host_collection_renders_node_labels_and_short_scrapes():
    chart = ROOT / "charts/prometheus-stack"
    result = subprocess.run(["helm", "template", "prometheus-eks-demo", str(chart), "-f", str(chart / "values.yaml"),
                             "-f", str(chart / "eks/values-eks-demo.yaml")], capture_output=True, text=True, check=True)
    docs = [doc for doc in yaml.safe_load_all(result.stdout) if doc]
    monitors = {doc["metadata"]["name"]: doc for doc in docs if doc["kind"] == "ServiceMonitor"}
    endpoint = monitors["prometheus-node-exporter"]["spec"]["endpoints"][0]
    assert endpoint["interval"] == "15s"
    assert {"action": "replace", "sourceLabels": ["__meta_kubernetes_pod_node_name"], "targetLabel": "node"} in endpoint["relabelings"]
    probes = next(e for e in monitors["prometheus-kubelet"]["spec"]["endpoints"] if e.get("path") == "/metrics/probes")
    assert probes["interval"] == "15s"
    exporter = next(doc for doc in docs if doc["kind"] == "DaemonSet"
                    and doc["metadata"]["name"] == "prometheus-node-exporter")
    args = exporter["spec"]["template"]["spec"]["containers"][0]["args"]
    assert any(arg.startswith("--collector.filesystem.mount-points-exclude=") for arg in args)
    assert any(arg.startswith("--collector.filesystem.fs-types-exclude=") for arg in args)


def test_eks_job_alerts_are_not_provisioned_on_k3s():
    values = yaml.safe_load((ROOT / "charts/grafana/k3s/values-k3s-demo.yaml").read_text())
    assert "node-health.yaml" not in values["grafana"].get("alerting", {})
