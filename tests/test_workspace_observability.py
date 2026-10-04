from pathlib import Path
import re
import subprocess

import yaml
from test_node_observability import rendered_grafana, run_promtool

ROOT = Path(__file__).resolve().parents[1]


def test_workspace_firing_alerts_reach_grafana_with_identity_and_severity(rendered_grafana, tmp_path):
    secret = next(doc for doc in rendered_grafana if "workspace-notifications.yaml" in (doc.get("stringData") or {}))
    rule = yaml.safe_load(secret["stringData"]["workspace-notifications.yaml"])["groups"][0]["rules"][0]
    expr = rule["data"][0]["model"]["expr"]
    fixture = {"evaluation_interval": "1m", "tests": [{"interval": "1m", "input_series": [
        {"series": 'ALERTS{alertname="StudioSandboxQuota",alertstate="firing",service="agent-studio",severity="warning",cluster="demo"}', "values": "1x5"},
        {"series": 'ALERTS{alertname="StudioSandboxPending",alertstate="pending",service="agent-studio",severity="warning",cluster="demo"}', "values": "1x5"},
        {"series": 'ALERTS{alertname="Unrelated",alertstate="firing",service="other",severity="critical",cluster="demo"}', "values": "1x5"},
    ], "promql_expr_test": [{"expr": expr, "eval_time": "5m", "exp_samples": [{
        "labels": '{cluster="demo",service="agent-studio",severity="warning",workspace_alert="StudioSandboxQuota"}', "value": 1,
    }]}]}]}
    (tmp_path / "tests.yaml").write_text(yaml.safe_dump(fixture))
    run_promtool(tmp_path)


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
    pattern = re.search(r'prometheus.relabel "retained_metrics"\s*\{.*?regex\s*=\s*"([^"]+)"', config, re.S).group(1)
    for series in ["workspace-state;up", "workspace-state;kube_pod_status_phase", "workspace-state;kube_resourcequota",
                   "workspace-state;kube_node_status_condition", "integrations/cadvisor;container_fs_usage_bytes",
                   "integrations/cadvisor;container_fs_limit_bytes", "kubelet;up",
                   "kubelet;kubelet_volume_stats_available_bytes", "agent-studio;agent_studio_build_info"]:
        assert re.fullmatch(pattern, series), series
    for series in ["workspace-state;unbounded_arbitrary_series", "kubelet;apiserver_request_duration_seconds_bucket",
                   "integrations/cadvisor;container_tasks_state"]:
        assert not re.fullmatch(pattern, series), series
    # Every source must cross the same filter before remote_write allocates WAL series.
    assert config.count("prometheus.remote_write.grafana_cloud.receiver") == 1
    assert "write_relabel_config" not in config
    assert config.count("prometheus.relabel.retained_metrics.receiver") == 6


def test_prometheus_rules_use_the_shared_policy_with_existing_node_labels():
    groups = yaml.safe_load((ROOT / "config/workspace-alerts.yaml").read_text())["groups"]
    chart = ROOT / "charts/prometheus-stack"
    output = subprocess.run(
        ["helm", "template", "prometheus-eks-demo", str(chart), "--namespace", "addon-prometheus",
         "-f", str(chart / "values.yaml"), "-f", str(chart / "eks/values-eks-demo.yaml")],
        capture_output=True, text=True,
    )
    assert output.returncode == 0, output.stderr
    docs = [doc for doc in yaml.safe_load_all(output.stdout) if doc]
    rule = next(doc for doc in docs if doc["kind"] == "PrometheusRule"
                and doc["metadata"]["name"] == "prometheus-agent-studio-workspaces")
    assert rule["spec"]["groups"] == groups
    prometheus = next(doc for doc in docs if doc["kind"] == "Prometheus")
    selector = prometheus["spec"]["ruleSelector"]["matchLabels"]
    assert selector
    assert all(rule["metadata"]["labels"].get(key) == value for key, value in selector.items())
    base = yaml.safe_load((ROOT / "charts/prometheus-stack/values.yaml").read_text())
    assert any("nodes=[*]" in arg for arg in base["kube-prometheus-stack"]["kube-state-metrics"]["extraArgs"])
