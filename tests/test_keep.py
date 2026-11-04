from pathlib import Path
import json
import subprocess

import yaml


ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "charts" / "keep"


def render():
    result = subprocess.run(
        ["helm", "template", "keep", str(CHART), "--namespace", "addon-keep",
         "-f", str(CHART / "values.yaml"), "-f", str(CHART / "eks" / "values-eks-demo.yaml")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def test_route_targets_the_frontend_service_port():
    docs = render()
    services = {doc["metadata"]["name"]: doc for doc in docs if doc["kind"] == "Service"}
    routes = [doc for doc in docs if doc["kind"] == "HTTPRoute"]
    assert [route["metadata"]["name"] for route in routes] == ["keep"]
    backends = [backend for rule in routes[0]["spec"]["rules"] for backend in rule["backendRefs"]]
    assert backends == [{"name": "keep-frontend", "port": 3000}]
    assert 3000 in {port["port"] for port in services["keep-frontend"]["spec"]["ports"]}


def test_secrets_survive_the_pre_delete_hook():
    # delete-keep-secrets deletes every Secret named keep-*. Only the chart's own
    # keep-providers may match; the ExternalSecret targets must not.
    docs = render()
    hook = next(doc for doc in docs if doc["kind"] == "Job" and doc["metadata"]["name"] == "delete-keep-secrets")
    assert "grep '^secret/keep-'" in hook["spec"]["template"]["spec"]["containers"][0]["command"][-1]
    targets = [doc["spec"]["target"]["name"] for doc in docs if doc["kind"] == "ExternalSecret"]
    assert targets and not [name for name in targets if name.startswith("keep-")]
    referenced = set()
    for doc in docs:
        if doc["kind"] != "Deployment":
            continue
        spec = doc["spec"]["template"]["spec"]
        for container in spec["containers"]:
            referenced |= {ref["secretRef"]["name"] for ref in container.get("envFrom", [])}
        referenced |= {volume["secret"]["secretName"] for volume in spec.get("volumes", []) if "secret" in volume}
    assert referenced - {"keep-providers"} <= set(targets)


def test_no_plain_text_secrets_and_websocket_disabled():
    docs = render()
    kinds = {(doc["kind"], doc["metadata"]["name"]) for doc in docs}
    assert ("Deployment", "keep-websocket") not in kinds
    for doc in docs:
        if doc["kind"] != "Deployment":
            continue
        for container in doc["spec"]["template"]["spec"]["containers"]:
            env = {item["name"]: item.get("value") for item in container.get("env", [])}
            assert not {"DATABASE_CONNECTION_STRING", "NEXTAUTH_SECRET", "POSTGRES_PASSWORD",
                        "PUSHER_APP_SECRET", "KEEP_OIDC_CLIENT_SECRET"} & env.keys(), doc["metadata"]["name"]
            if "PUSHER_DISABLED" in env:
                assert env["PUSHER_DISABLED"] == "true"


def test_provisioned_providers_read_cluster_services_without_webhooks():
    docs = render()
    secret = next(doc for doc in docs if doc["kind"] == "Secret" and doc["metadata"]["name"] == "keep-providers")
    providers = json.loads(secret["stringData"]["KEEP_PROVIDERS"])
    assert {name: provider["type"] for name, provider in providers.items()} == {
        "prometheus": "prometheus", "loki": "grafana_loki", "argocd": "argocd",
    }
    assert all(provider["install_webhook"] is False for provider in providers.values())
    assert providers["argocd"]["authentication"]["argocd_access_token"] == "$(ARGOCD_ACCESS_TOKEN)"


def test_backend_keeps_the_trace_id_middleware():
    # KEEP_OTEL_ENABLED=false skips keep.api.observability.setup, which sets
    # request.state.trace_id; POST /alerts/event then fails with 500. Without an
    # OTLP endpoint the setup installs no exporter.
    docs = render()
    backend = next(doc for doc in docs if doc["kind"] == "Deployment" and doc["metadata"]["name"] == "keep-backend")
    env = {item["name"]: item.get("value") for item in backend["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env.get("KEEP_OTEL_ENABLED", "true") == "true"
    assert "OTEL_EXPORTER_OTLP_ENDPOINT" not in env
