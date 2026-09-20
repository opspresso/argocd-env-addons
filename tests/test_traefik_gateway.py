from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

from workload_policy import policy_errors


ROOT = Path(__file__).resolve().parents[1]


def test_traefik_embedded_values_preserve_resource_mapping():
    if not shutil.which("helm"):
        pytest.skip("Helm is required to validate deployment manifests")
    chart = ROOT / "charts/traefik-gateway"
    result = subprocess.run(
        ["helm", "template", "traefik-gateway-k3s", str(chart), "-f", str(chart / "k3s/values-k3s-demo.yaml")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert policy_errors(result.stdout, "k3s") == []
    config = next(doc for doc in yaml.safe_load_all(result.stdout) if doc and doc["kind"] == "HelmChartConfig")
    values = yaml.safe_load(config["spec"]["valuesContent"])
    assert values["resources"] == {"requests": None, "limits": None}
    assert values["providers"]["kubernetesGateway"]["enabled"] is True
