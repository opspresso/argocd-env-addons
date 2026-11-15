from functools import cache
from pathlib import Path
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]


@cache
def manifests():
    chart = ROOT / "charts/nexus"
    result = subprocess.run(
        ["helm", "template", "nexus", str(chart), "--namespace", "addon-nexus",
         "-f", str(chart / "values.yaml"), "-f", str(chart / "eks/values-eks-demo.yaml")],
        capture_output=True, text=True, check=True,
    )
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def spec(kind):
    return next(doc["spec"] for doc in manifests() if doc["kind"] == kind)


@pytest.mark.parametrize("path", [
    "/service/rest/v1/assets", "/service/rest/v1/assets/asset-id", "/v2", "/v2/", "/v2/runway-images/app/manifests/release-1",
    "/v2/runway-images/app/blobs/uploads/", "/repository/releases/app.jar",
])
def test_package_clients_reach_nexus_without_trusting_user_headers(path):
    exclusions = spec("AuthorizationPolicy")["rules"][0]["to"][0]["operation"]["notPaths"]
    assert any(path.startswith(p[:-1]) if p.endswith("*") else path == p for p in exclusions)
    for rule in spec("HTTPRoute")["rules"]:
        if any(path == m["path"]["value"].rstrip("/") or
               path.startswith(m["path"]["value"].rstrip("/") + "/")
               for m in rule.get("matches", [])):
            removed = rule["filters"][0]["requestHeaderModifier"]["remove"]
            assert "X-Auth-Request-Preferred-Username" in removed
            assert rule["backendRefs"][0]["name"] == "nexus"
            return
    pytest.fail(f"No credential-safe client route for {path}")


@pytest.mark.parametrize("path", ["/", "/service/rest/v1/security/users", "/v2evil", "/repositoryevil", "/service/rest/v1/assets-evil"])
def test_ui_and_management_api_still_require_sso(path):
    exclusions = spec("AuthorizationPolicy")["rules"][0]["to"][0]["operation"]["notPaths"]
    assert not any(path.startswith(p[:-1]) if p.endswith("*") else path == p for p in exclusions)
