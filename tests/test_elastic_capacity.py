from pathlib import Path

import yaml

from test_node_observability import run_promtool

ROOT = Path(__file__).resolve().parents[1]


def test_quota_alerts_exclude_only_the_elastic_workspace_namespace(tmp_path):
    config = yaml.safe_load((ROOT / "charts/prometheus-stack/values.yaml").read_text())["kube-prometheus-stack"]
    rules = config["additionalPrometheusRulesMap"]["nonelastic-quota-capacity"]["groups"][0]["rules"]
    tests = []
    for rule, resource in zip(rules, ("cpu", "memory"), strict=True):
        for static, expected in [(10, []), (20, [{"labels": '{cluster="demo"}', "value": 2}])]:
            tests.append({"interval": "1m", "input_series": [
                {"series": f'kube_resourcequota{{cluster="demo",namespace="agent-studio-workspaces",job="kube-state-metrics",resource="requests.{resource}",type="hard"}}', "values": "100x5"},
                {"series": f'kube_resourcequota{{cluster="demo",namespace="fixed",job="kube-state-metrics",resource="requests.{resource}",type="hard"}}', "values": f"{static}x5"},
                {"series": f'kube_node_status_allocatable{{cluster="demo",job="kube-state-metrics",resource="{resource}"}}', "values": "10x5"},
            ], "promql_expr_test": [{"expr": rule["expr"], "eval_time": "5m", "exp_samples": expected}]})
    (tmp_path / "tests.yaml").write_text(yaml.safe_dump({"evaluation_interval": "1m", "tests": tests}))
    run_promtool(tmp_path)
