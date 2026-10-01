"""Exercise rendered alert rules and actual dashboard queries, including empty workloads."""
import json
from pathlib import Path

import yaml

from test_node_observability import rendered_grafana, run_promtool

ROOT = Path(__file__).resolve().parents[1]


def source_query(panel_id, ref="A", **variables):
    board = json.loads((ROOT / "charts/grafana/dashboards/kube-workload.json").read_text())
    if isinstance(panel_id, str):
        variable = next(v for v in board["templating"]["list"] if v["name"] == panel_id)
        query = variable["definition"][len("query_result("):-1]
    else:
        panel = next(p for p in board["panels"] if p["id"] == panel_id)
        query = next(t["expr"] for t in panel["targets"] if t["refId"] == ref)
    values = {"cluster": "demo", "namespace": "apps", "workload": "shared", "workload_type": "statefulset", "service": ".*", **variables}
    for key in sorted(values, key=len, reverse=True):
        query = query.replace("$" + key, values[key])
    return query


def test_workload_rules_and_scoped_panels(rendered_grafana, tmp_path):
    secret = next(doc for doc in rendered_grafana if "workload-health.yaml" in (doc.get("stringData") or {}))
    config = yaml.safe_load(secret["stringData"]["workload-health.yaml"])
    rules = []
    for rule in config["groups"][0]["rules"]:
        query, condition = rule["data"]
        evaluator = condition["model"]["conditions"][0]["evaluator"]
        operator = {"gt": ">", "lt": "<"}[evaluator["type"]]
        rules.append({"alert": rule["uid"], "expr": f'({query["model"]["expr"]}) {operator} {evaluator["params"][0]}', "for": rule["for"]})
    (tmp_path / "rules.yaml").write_text(yaml.safe_dump({"groups": [{"name": "workload-health", "interval": "30s", "rules": rules}]}))
    cases = yaml.safe_load((ROOT / "tests/workload-health-alerts.test.yaml").read_text())
    # The fixture defines expected results; queries come from the shipped JSON.
    for case in cases["tests"]:
        for expectation in case.get("promql_expr_test", []):
            selector = expectation.pop("dashboard_query", None)
            if selector:
                expectation["expr"] = source_query(**selector)
            variable = expectation.pop("dashboard_variable", None)
            if variable:
                expectation["expr"] = source_query(variable)
    (tmp_path / "tests.yaml").write_text(yaml.safe_dump(cases))
    run_promtool(tmp_path)


def test_provisioning_has_unique_uids_and_links_to_existing_panels(rendered_grafana):
    boards = {uid: json.loads((ROOT / f"charts/grafana/dashboards/{uid}.json").read_text()) for uid in ["kube-cluster", "kube-workload"]}
    uids = set()
    for doc in rendered_grafana:
        for name, content in (doc.get("stringData") or {}).items():
            if not name.endswith(".yaml"):
                continue
            config = yaml.safe_load(content)
            for group in config.get("groups", []):
                for rule in group["rules"]:
                    assert rule["uid"] not in uids, rule["uid"]
                    uids.add(rule["uid"])
                    a = rule.get("annotations", {})
                    if "__dashboardUid__" in a:
                        ids = {str(p["id"]) for p in boards[a["__dashboardUid__"]]["panels"]}
                        assert a["__panelId__"] in ids
                    if "dashboard_url" in a:
                        assert a["dashboard_url"].startswith("https://grafana.demo.opspresso.com/d/kube-workload?")
                        assert "{{ $labels.namespace }}" in a["dashboard_url"]
                        assert '{{ "' not in a["dashboard_url"]
