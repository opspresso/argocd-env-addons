from pathlib import Path
import re
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_k3s_exporter_exposes_only_required_read_only_state():
    chart = ROOT / "charts/workspace-metrics"
    output = subprocess.run(["helm", "template", "workspace-metrics", str(chart),
                             "-f", str(chart / "values.yaml"), "-f", str(chart / "k3s/values-k3s-demo.yaml")],
                            capture_output=True, text=True)
    assert output.returncode == 0, output.stderr
    output = output.stdout
    docs = [doc for doc in yaml.safe_load_all(output) if doc]
    role = next(doc for doc in docs if doc["kind"] == "ClusterRole")
    assert {resource for rule in role["rules"] for resource in rule["resources"]} == {"pods", "nodes", "resourcequotas", "deployments"}
    assert all(set(rule["verbs"]) == {"list", "watch"} for rule in role["rules"])
    container = next(doc for doc in docs if doc["kind"] == "Deployment")["spec"]["template"]["spec"]["containers"][0]
    assert "--namespaces=agent-studio,agent-studio-workspaces" in container["args"]
    assert not container.get("resources")


def test_cloud_filter_retains_workspace_state_and_disk_metrics_without_accepting_arbitrary_series():
    values = yaml.safe_load((ROOT / "charts/alloy/k3s/values-k3s-demo.yaml").read_text())
    config = values["alloy"]["alloy"]["configMap"]["content"]
    pattern = re.search(r'write_relabel_config\s*\{.*?regex\s*=\s*"([^"]+)"', config, re.S).group(1)
    for series in ["workspace-state;up", "workspace-state;kube_pod_status_phase", "workspace-state;kube_resourcequota",
                   "workspace-state;kube_node_status_condition", "integrations/cadvisor;container_fs_usage_bytes",
                   "integrations/cadvisor;container_fs_limit_bytes"]:
        assert re.fullmatch(pattern, series), series
    assert not re.fullmatch(pattern, "workspace-state;unbounded_arbitrary_series")


def test_prometheus_rules_use_the_shared_policy_with_existing_node_labels():
    groups = yaml.safe_load((ROOT / "config/workspace-alerts.yaml").read_text())["groups"]
    values = yaml.safe_load((ROOT / "charts/prometheus-stack/eks/values-eks-demo.yaml").read_text())
    assert values["workspaceAlerts"]["groups"] == groups
    base = yaml.safe_load((ROOT / "charts/prometheus-stack/values.yaml").read_text())
    assert any("nodes=[*]" in arg for arg in base["kube-prometheus-stack"]["kube-state-metrics"]["extraArgs"])
