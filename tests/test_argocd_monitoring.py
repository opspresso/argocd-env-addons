from pathlib import Path
import subprocess

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_argocd_monitoring_matches_the_cluster_prometheus():
    chart = ROOT / "charts/argo-cd"
    result = subprocess.run([
        "helm", "template", "argocd", str(chart),
        "-f", str(chart / "values.yaml"), "-f", str(chart / "eks/values-eks-demo.yaml"),
        "--api-versions", "monitoring.coreos.com/v1",
    ], capture_output=True, text=True, check=True)
    documents = [item for item in yaml.safe_load_all(result.stdout) if item]
    monitors = [item for item in documents if item["kind"] == "ServiceMonitor"]
    assert monitors
    assert all(item["metadata"]["labels"]["release"] == "prometheus-eks-demo" for item in monitors)
    assert any(item["kind"] == "Deployment" and item["metadata"]["name"] == "argocd-server" for item in documents)


def test_keep_gets_only_sync_failures_from_notifications():
    # Degraded and Unknown are short during installs and deletions, and a
    # deleted application never sends its recovery. Grafana rules alert on them
    # after they persist.
    values = yaml.safe_load((ROOT / "charts/argo-cd/eks/values-eks-demo.yaml").read_text())
    subscriptions = values["argo-cd"]["notifications"]["subscriptions"]
    assert subscriptions == [{"recipients": ["keep"], "triggers": ["on-keep-sync"]}]
    common = yaml.safe_load((ROOT / "charts/argo-cd/values.yaml").read_text())["argo-cd"]["notifications"]
    assert {key for key in common["triggers"] if "keep" in key} == {"trigger.on-keep-sync"}
    assert {key for key in common["templates"] if "keep" in key} == {"template.keep-app-sync"}
