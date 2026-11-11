"""Critical addons run on the on-demand core nodes of eks-demo; other clusters keep their placement."""
from pathlib import Path
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
CORE = {"key": "opspresso.com/tier", "operator": "In", "values": ["core"]}
TOLERATION = {"key": "opspresso.com/tier", "operator": "Equal", "value": "core", "effect": "NoSchedule"}


def workloads(chart, cluster):
    path = ROOT / "charts" / chart
    result = subprocess.run(
        ["helm", "template", chart, str(path), "-f", str(path / "values.yaml"), "-f", str(path / "eks" / f"values-{cluster}.yaml")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    return {doc["metadata"]["name"]: doc["spec"]["template"] for doc in yaml.safe_load_all(result.stdout)
            if doc and doc["kind"] in ("Deployment", "StatefulSet")}


@pytest.mark.parametrize("chart,name", [("istio", "istiod"), ("istio", "istio-ingressgateway"), ("dex", "dex")])
def test_replicated_addons_prefer_core_and_spill_over(chart, name):
    spec = workloads(chart, "eks-demo")[name]["spec"]
    assert TOLERATION in spec["tolerations"]
    node = spec["affinity"]["nodeAffinity"]
    # Preferred only: HPA growth and rollout surge must still schedule on Spot when core is full.
    assert "requiredDuringSchedulingIgnoredDuringExecution" not in node
    assert node["preferredDuringSchedulingIgnoredDuringExecution"] == [{"weight": 100, "preference": {"matchExpressions": [CORE]}}]


def test_lldap_requires_core_and_blocks_voluntary_disruption():
    template = workloads("lldap", "eks-demo")["lldap"]
    terms = template["spec"]["affinity"]["nodeAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"]["nodeSelectorTerms"]
    assert terms == [{"matchExpressions": [CORE]}]
    assert TOLERATION in template["spec"]["tolerations"]
    assert template["metadata"]["annotations"]["karpenter.sh/do-not-disrupt"] == "true"


@pytest.mark.parametrize("cluster", ["eks-demo-a", "eks-demo-b"])
def test_clusters_without_core_nodes_keep_istio_unpinned(cluster):
    for name, template in workloads("istio", cluster).items():
        assert "affinity" not in template["spec"], name
