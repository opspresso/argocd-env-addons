import base64
import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import patch

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "install/local/credentials.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("local_credentials", SCRIPT)
credentials = importlib.util.module_from_spec(spec)
spec.loader.exec_module(credentials)


def sources():
    return {name: {"data": {key: base64.b64encode(f"fixture-{key}".encode()).decode() for key in keys}}
            for name, keys in {
                "local-credentials": ["POSTGRES_PASSWORD", "MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD", "NEO4J_AUTH"],
                "local-mcp-argocd": ["ARGOCD_API_TOKEN"],
            }.items()}


def test_projection_preserves_existing_bytes_and_scopes_targets():
    original = sources()
    targets = credentials.projected_secrets(original)
    assert {s["metadata"]["namespace"] for s in targets} == {"agent-studio", "agent-memory", "agent-mcps"}
    postgres = next(s for s in targets if s["metadata"]["name"] == "postgresql-credentials")
    assert postgres["data"] == {"password": original["local-credentials"]["data"]["POSTGRES_PASSWORD"],
                                "postgres-password": original["local-credentials"]["data"]["POSTGRES_PASSWORD"]}
    token = next(s for s in targets if s["metadata"]["name"] == "mcp-argocd-external")
    assert token["data"] == original["local-mcp-argocd"]["data"]


@pytest.mark.parametrize("value", ["", "REPLACE_PASSWORD", "neo4j/REPLACE_NEO4J_PASSWORD"])
def test_empty_or_placeholder_values_are_rejected(value):
    original = sources()
    original["local-credentials"]["data"]["NEO4J_AUTH"] = base64.b64encode(value.encode()).decode()
    with pytest.raises(ValueError, match="Set NEO4J_AUTH"):
        credentials.projected_secrets(original)


def test_existing_secret_difference_stops_before_any_write():
    original = sources()

    def read(args, **_kwargs):
        name = args[args.index("get") + 2]
        if name in original:
            return json.dumps(original[name])
        return json.dumps({"data": {"password": "different-value"}})

    with patch.object(sys, "argv", [str(SCRIPT), "orbstack"]), \
            patch.object(credentials.subprocess, "check_output", side_effect=read), \
            patch.object(credentials.subprocess, "run") as write:
        with pytest.raises(ValueError, match="coordinate credential rotation"):
            credentials.main()
        write.assert_not_called()
