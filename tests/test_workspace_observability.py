from pathlib import Path
import json
import re
import subprocess

import pytest
import yaml
from test_node_observability import rendered_grafana, run_promtool

ROOT = Path(__file__).resolve().parents[1]


def test_workspace_firing_alerts_reach_grafana_with_identity_and_severity(rendered_grafana, tmp_path):
    secret = next(doc for doc in rendered_grafana if "workspace-notifications.yaml" in (doc.get("stringData") or {}))
    rule = yaml.safe_load(secret["stringData"]["workspace-notifications.yaml"])["groups"][0]["rules"][0]
    expr = rule["data"][0]["model"]["expr"]
    fixture = {"evaluation_interval": "1m", "tests": [{"interval": "1m", "input_series": [
        {"series": 'ALERTS{alertname="ForgeSandboxQuota",alertstate="firing",service="agent-forge",severity="warning",cluster="demo"}', "values": "1x5"},
        {"series": 'ALERTS{alertname="ForgeSandboxPending",alertstate="pending",service="agent-forge",severity="warning",cluster="demo"}', "values": "1x5"},
        {"series": 'ALERTS{alertname="LibrioWorkerUnavailable",alertstate="firing",service="agent-librio",severity="critical",cluster="demo"}', "values": "1x5"},
        {"series": 'ALERTS{alertname="ForgeServiceUnavailable",alertstate="firing",service="agent-forge",severity="critical",cluster="demo"}', "values": "1x5"},
        {"series": 'ALERTS{alertname="Unrelated",alertstate="firing",service="other",severity="critical",cluster="demo"}', "values": "1x5"},
    ], "promql_expr_test": [{"expr": expr, "eval_time": "5m", "exp_samples": [{
        "labels": '{cluster="demo",service="agent-forge",severity="warning",workspace_alert="ForgeSandboxQuota"}', "value": 1,
    }, {
        "labels": '{cluster="demo",service="agent-librio",severity="critical",workspace_alert="LibrioWorkerUnavailable"}', "value": 1,
    }, {
        "labels": '{cluster="demo",service="agent-forge",severity="critical",workspace_alert="ForgeServiceUnavailable"}', "value": 1,
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
    assert "--namespaces=agent-studio,agent-librio,agent-forge,agent-forge-workspaces" in container["args"]
    assert not container.get("resources")


def test_cloud_filter_retains_workspace_state_and_disk_metrics_without_accepting_arbitrary_series():
    values = yaml.safe_load((ROOT / "charts/alloy/k3s/values-k3s-demo.yaml").read_text())
    config = values["alloy"]["alloy"]["configMap"]["content"]
    pattern = re.search(r'prometheus.relabel "retained_metrics"\s*\{.*?regex\s*=\s*"([^"]+)"', config, re.S).group(1)
    for series in ["workspace-state;up", "workspace-state;kube_pod_status_phase", "workspace-state;kube_resourcequota",
                   "workspace-state;kube_node_status_condition", "integrations/cadvisor;container_fs_usage_bytes",
                   "integrations/cadvisor;container_fs_limit_bytes", "kubelet;up",
                   "kubelet;kubelet_volume_stats_available_bytes", "agent-studio;agent_studio_build_info",
                   "agent-librio;agent_librio_build_info", "agent-forge;agent_forge_active_model_requests"]:
        assert re.fullmatch(pattern, series), series
    for series in ["workspace-state;unbounded_arbitrary_series", "kubelet;apiserver_request_duration_seconds_bucket",
                   "integrations/cadvisor;container_tasks_state"]:
        assert not re.fullmatch(pattern, series), series
    # Every source must cross the same filter before remote_write allocates WAL series.
    assert config.count("prometheus.remote_write.grafana_cloud.receiver") == 1
    replay_pattern = re.search(r'prometheus.remote_write "grafana_cloud"\s*\{.*?write_relabel_config\s*\{.*?regex\s*=\s*"([^"]+)"', config, re.S).group(1)
    assert replay_pattern == pattern
    assert config.count("prometheus.relabel.retained_metrics.receiver") == 8


@pytest.mark.parametrize("namespace,pod,expected", [
    ("agent-forge-workspaces", "forge-ws-51e2938a2963c2657e94d57f731adcc6b12a7b9a-w2lmz", True),
    ("agent-forge-workspaces", "forge-ws-" + "f" * 40 + "-9x66c", True),
    ("other", "forge-ws-" + "a1" * 20 + "-jrg8w", False),
    ("", "forge-ws-" + "a1" * 20 + "-jrg8w", False),
    ("agent-forge-workspaces", "forge-ws-" + "a1" * 20, False),
    ("agent-forge-workspaces", "forge-ws-" + "a" * 39 + "-jrg8w", False),
    ("agent-forge-workspaces", "forge-ws-" + "g" * 40 + "-jrg8w", False),
    ("agent-forge-workspaces", "forge-ws-" + "A" * 40 + "-jrg8w", False),
    ("agent-forge-workspaces", "forge-ws-" + "a" * 40 + "-jrg8wx", False),
    ("agent-forge-workspaces", "forge-ws-" + "a" * 40 + "-jrg8w-extra", False),
    ("agent-forge-workspaces", "agent-forge-worker-abc12-def34", False),
])
def test_cadvisor_classifies_only_forge_controller_pods(namespace, pod, expected):
    values = yaml.safe_load((ROOT / "charts/alloy/k3s/values-k3s-demo.yaml").read_text())
    config = values["alloy"]["alloy"]["configMap"]["content"]
    cadvisor = re.search(r'prometheus.relabel "cadvisor" \{(.*?)^\}', config, re.S | re.M).group(1)
    rules = re.findall(r'^  rule \{(.*?)^  \}', cadvisor, re.S | re.M)
    rule = next(rule for rule in rules if 'replacement   = "agent-forge-sandbox"' in rule)
    sources = json.loads(re.search(r'source_labels\s*=\s*(\[[^\]]+\])', rule).group(1))
    separator = re.search(r'separator\s*=\s*"([^"]+)"', rule)
    separator = separator.group(1) if separator else ";"
    pattern = re.search(r'regex\s*=\s*"([^"]+)"', rule).group(1)
    labels = {"namespace": namespace, "pod": pod}
    assert bool(re.fullmatch(pattern, separator.join(labels[name] for name in sources))) is expected


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
                and doc["metadata"]["name"] == "prometheus-agent-platform-workloads")
    assert rule["spec"]["groups"] == groups
    prometheus = next(doc for doc in docs if doc["kind"] == "Prometheus")
    selector = prometheus["spec"]["ruleSelector"]["matchLabels"]
    assert selector
    assert all(rule["metadata"]["labels"].get(key) == value for key, value in selector.items())
    base = yaml.safe_load((ROOT / "charts/prometheus-stack/values.yaml").read_text())
    assert any("nodes=[*]" in arg for arg in base["kube-prometheus-stack"]["kube-state-metrics"]["extraArgs"])


def test_platform_alerts_evaluate_owner_failure_maintenance_and_cluster_boundaries(tmp_path):
    (tmp_path / "rules.yaml").write_text((ROOT / "config/workspace-alerts.yaml").read_text())
    fixture = yaml.safe_load((ROOT / "tests/workspace-alerts.test.yaml").read_text())
    fixture["rule_files"] = ["rules.yaml"]
    (tmp_path / "tests.yaml").write_text(yaml.safe_dump(fixture))
    run_promtool(tmp_path)


def test_application_scrapes_use_separate_credentials_and_exporter_roles():
    values = yaml.safe_load((ROOT / "charts/alloy/k3s/values-k3s-demo.yaml").read_text())
    config = values["alloy"]["alloy"]["configMap"]["content"]
    targets = {}
    for name in ("agent_studio", "agent_memory", "agent_librio", "agent_forge"):
        block = re.search(r'prometheus.scrape "' + name + r'" \{(.*?)^\}', config, re.S | re.M).group(1)
        targets[name] = re.findall(r'"__address__"\s*=\s*"([^\"]+)"', block)
        assert f'"namespace"   = "{name.replace("_", "-")}"' in block
        if name != "agent_studio":
            assert f'bearer_token    = sys.env("{name.upper()}_METRICS_BEARER_TOKEN")' in block
        path = "/metrics" if name == "agent_forge" else "/api/metrics"
        assert f'metrics_path    = "{path}"' in block
    assert targets == {
        "agent_studio": ["agent-studio.agent-studio.svc:3000"],
        "agent_memory": ["agent-memory.agent-memory.svc:3000"],
        "agent_librio": ["agent-librio.agent-librio.svc:3000", "agent-librio-worker.agent-librio.svc:3000"],
        "agent_forge": ["agent-forge.agent-forge.svc:3103"],
    }
    assert '"component"   = "worker"' in config
    secret = next(resource for resource in values["raw"]["resources"]
                  if resource["kind"] == "ExternalSecret" and resource["metadata"]["name"] == "alloy-grafana-cloud")
    paths = {entry["secretKey"]: entry["remoteRef"]["key"] for entry in secret["spec"]["data"]}
    for service in ("MEMORY", "LIBRIO", "FORGE"):
        assert paths[f"AGENT_{service}_METRICS_BEARER_TOKEN"] == f"/k8s/k3s-demo/agent-{service.lower()}/metrics-bearer-token"
    assert all("delegation" not in value and "policy" not in value for value in paths.values())


def test_capacity_dashboard_separates_control_plane_and_execution_load(tmp_path):
    dashboard = json.loads((ROOT / "charts/grafana/dashboards/workspace-capacity.json").read_text())
    panels = {panel["id"]: panel for panel in dashboard["panels"]}
    series = [
        {"series": 'agent_studio_active_execution_requests{cluster="demo",namespace="agent-studio"}', "values": "3x5"},
        {"series": 'agent_forge_active_model_requests{cluster="demo",namespace="agent-forge"}', "values": "2x5"},
        {"series": 'agent_forge_active_model_requests{cluster="other",namespace="agent-forge"}', "values": "99x5"},
        {"series": 'kube_resourcequota{cluster="demo",namespace="agent-forge-workspaces",resource="pods",type="used"}', "values": "2x5"},
        {"series": 'kube_resourcequota{cluster="demo",namespace="agent-forge-workspaces",resource="pods",type="hard"}', "values": "8x5"},
        {"series": 'kube_resourcequota{cluster="demo",namespace="agent-studio-workspaces",resource="pods",type="used"}', "values": "99x5"},
    ]
    checks = [{"expr": panels[identifier]["targets"][0]["expr"].replace("$cluster", "demo"),
               "eval_time": "5m", "exp_samples": [{"labels": "{}", "value": value}]}
              for identifier, value in [(1, 25), (2, 2), (4, 3), (11, 2)]]
    (tmp_path / "tests.yaml").write_text(yaml.safe_dump({"evaluation_interval": "1m", "tests": [
        {"interval": "1m", "input_series": series, "promql_expr_test": checks},
    ]}))
    run_promtool(tmp_path)
