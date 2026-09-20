import importlib.util
from pathlib import Path
import sys
from unittest.mock import Mock, patch

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "install/local"
sys.path.insert(0, str(SCRIPT_DIR))
spec = importlib.util.spec_from_file_location("local_connect", SCRIPT_DIR / "connect.py")
connect = importlib.util.module_from_spec(spec)
spec.loader.exec_module(connect)
from runtime import resolve_context


@pytest.mark.parametrize("context", ["orbstack", "docker-desktop"])
def test_supported_contexts_are_forwarded_explicitly(context):
    assert resolve_context(context) == context
    services = yaml.safe_load((SCRIPT_DIR / "connections.yaml").read_text())
    ports = []
    for service in services.values():
        command = connect.command(context, service)
        assert command[:3] == ["kubectl", "--context", context]
        assert command[command.index("--address") + 1] == "127.0.0.1"
        assert f"service/{service['service']}" in command
        ports.extend(mapping.split(":")[0] for mapping in service["ports"])
    assert len(ports) == len(set(ports))


def test_remote_context_is_rejected_before_any_cluster_command(monkeypatch):
    monkeypatch.setenv("KUBE_CONTEXT", "production")
    with patch("runtime.subprocess.check_output") as query:
        with pytest.raises(ValueError, match="Local deployment requires"):
            resolve_context()
        query.assert_not_called()


def test_current_context_is_validated(monkeypatch):
    monkeypatch.delenv("KUBE_CONTEXT", raising=False)
    with patch("runtime.subprocess.check_output", return_value="docker-desktop\n"):
        assert resolve_context() == "docker-desktop"
    with patch("runtime.subprocess.check_output", return_value="production\n"):
        with pytest.raises(ValueError):
            resolve_context()


def test_port_collision_is_reported_and_preflight_socket_is_closed():
    listener = Mock()
    listener.bind.side_effect = OSError("address in use")
    with patch.object(connect.socket, "socket", return_value=listener):
        with pytest.raises(RuntimeError, match="5432 is unavailable"):
            connect.check_ports({"postgres": {"ports": ["5432:5432"]}})
    listener.close.assert_called_once()
