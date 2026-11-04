from pathlib import Path
import json
import subprocess

import yaml
from test_node_observability import rendered_grafana, run_promtool

ROOT = Path(__file__).resolve().parents[1]


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
