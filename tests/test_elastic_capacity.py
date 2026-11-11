"""Capacity alerts follow the NodePool ceiling, not the current node count."""
from pathlib import Path

import yaml

from test_node_observability import run_promtool

ROOT = Path(__file__).resolve().parents[1]
VALUES = yaml.safe_load((ROOT / "charts/prometheus-stack/values.yaml").read_text())["kube-prometheus-stack"]


def node(name, pool, cpu):
    return [
        {"series": f'kube_node_status_capacity{{cluster="demo",job="kube-state-metrics",node="{name}",resource="cpu"}}',
         "values": f"{cpu}x20"},
        {"series": f'kube_node_labels{{cluster="demo",job="kube-state-metrics",node="{name}",label_karpenter_sh_nodepool="{pool}"}}',
         "values": "1x20"},
    ]


def test_nodepool_alert_fires_near_the_pool_limit_only(tmp_path):
    groups = VALUES["additionalPrometheusRulesMap"]["nodepool-capacity"]["groups"]
    (tmp_path / "rules.yaml").write_text(yaml.safe_dump({"groups": groups}))
    series = (node("a1", "full", 8) + node("a2", "full", 7)      # 15 of 16 CPU: 94%
              + node("b1", "roomy", 8)                            # 8 of 16 CPU: 50%
              + node("c1", "unbounded", 64)                       # no limit, no series
              + [{"series": 'karpenter_nodepool_limit{cluster="demo",nodepool="full",resource="cpu"}', "values": "16x20"},
                 {"series": 'karpenter_nodepool_limit{cluster="demo",nodepool="roomy",resource="cpu"}', "values": "16x20"}])
    tests = {"rule_files": ["rules.yaml"], "evaluation_interval": "1m", "tests": [{
        "interval": "1m", "input_series": series,
        "alert_rule_test": [
            {"eval_time": "10m", "alertname": "NodePoolNearLimit", "exp_alerts": []},
            {"eval_time": "16m", "alertname": "NodePoolNearLimit", "exp_alerts": [{
                "exp_labels": {"cluster": "demo", "nodepool": "full", "resource": "cpu", "severity": "warning"},
                "exp_annotations": {
                    "summary": "NodePool full uses 94% of its cpu limit.",
                    "description": VALUES["additionalPrometheusRulesMap"]["nodepool-capacity"]["groups"][0]["rules"][0]["annotations"]["description"],
                }}]},
        ]}]}
    (tmp_path / "tests.yaml").write_text(yaml.safe_dump(tests))
    run_promtool(tmp_path)


def test_bundled_rules_do_not_repeat_grafana_or_elastic_capacity_alerts():
    disabled = {name for name, off in VALUES["defaultRules"]["disabled"].items() if off}
    # Grafana rules own these symptoms; Auto Mode makes the capacity ratios meaningless.
    assert {"KubePodCrashLooping", "KubeNodeNotReady", "KubeCPUOvercommit", "KubeMemoryQuotaOvercommit",
            "KubeletTooManyPods"} <= disabled
    # The stack still watches itself.
    assert not disabled & {"Watchdog", "TargetDown", "PrometheusRuleFailures", "AlertmanagerFailedToSendAlerts"}
