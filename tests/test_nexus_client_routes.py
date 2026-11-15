from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
RESOURCES = yaml.safe_load(
    (ROOT / "charts/nexus/eks/values-eks-demo.yaml").read_text()
)["raw"]["resources"]
ROUTE = next(r["spec"] for r in RESOURCES if r["kind"] == "HTTPRoute")
POLICY = next(r["spec"] for r in RESOURCES if r["kind"] == "AuthorizationPolicy")


@pytest.mark.parametrize("path", [
    "/v2", "/v2/", "/v2/runway-images/app/manifests/release-1",
    "/v2/runway-images/app/blobs/uploads/", "/repository/releases/app.jar",
])
def test_package_clients_reach_nexus_without_trusting_user_headers(path):
    exclusions = POLICY["rules"][0]["to"][0]["operation"]["notPaths"]
    assert any(path.startswith(p[:-1]) if p.endswith("*") else path == p for p in exclusions)
    for rule in ROUTE["rules"]:
        if any(path == m["path"]["value"].rstrip("/") or
               path.startswith(m["path"]["value"].rstrip("/") + "/")
               for m in rule.get("matches", [])):
            removed = rule["filters"][0]["requestHeaderModifier"]["remove"]
            assert "X-Auth-Request-Preferred-Username" in removed
            assert rule["backendRefs"][0]["name"] == "nexus"
            return
    pytest.fail(f"No credential-safe client route for {path}")


@pytest.mark.parametrize("path", ["/", "/service/rest/v1/security/users", "/v2evil", "/repositoryevil"])
def test_ui_and_management_api_still_require_sso(path):
    exclusions = POLICY["rules"][0]["to"][0]["operation"]["notPaths"]
    assert not any(path.startswith(p[:-1]) if p.endswith("*") else path == p for p in exclusions)
