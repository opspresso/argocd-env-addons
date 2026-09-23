import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


INSTALL_DIR = Path(__file__).resolve().parents[1]
PASSWORD = "fixture password * [abc] $value"

COMMAND = r'''
import json
import os
from pathlib import Path
import sys

name = Path(sys.argv[0]).name
args = sys.argv[1:]
log = Path(os.environ["COMMAND_LOG"])
previous = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
with log.open("a") as stream:
    stream.write(json.dumps([name, *args]) + "\n")
scenario = os.environ.get("SCENARIO", "ready")

if name == "aws":
    parameter = args[args.index("--name") + 1].rsplit("/", 1)[-1]
    if parameter == os.environ.get("FAIL_PARAMETER"):
        if scenario == "ssm_failure":
            print("AccessDeniedException", file=sys.stderr)
            sys.exit(254)
        print(json.dumps({"Parameter": {"Value": None if scenario == "ssm_null" else ""}}))
        sys.exit()
    values = {
        "admin-user": "admin",
        "admin-password": os.environ["FIXTURE_PASSWORD"],
        "argocd-password": "$2a$10$fixture-hash",
        "argocd-mtime": "2026-01-01T00:00:00Z",
    }
    print(json.dumps({"Parameter": {"Value": values[parameter]}}))
elif name == "curl":
    count = sum(command[0] == "curl" for command in previous)
    if scenario == "timeout":
        print("503", end="")
    elif scenario == "recover" and count == 0:
        print("000", end="")
        sys.exit(60)
    else:
        print("200", end="")
elif name == "argocd" and scenario == "login_failure":
    sys.exit(20)
'''


def run_installer(tmp_path, scenario="ready", parameter="admin-password", timeout="20"):
    target = tmp_path / "install" / "k3s"
    shutil.copytree(INSTALL_DIR, target)
    (tmp_path / "env").mkdir()
    (tmp_path / "env" / "k3s-demo.yaml").write_text("argocd:\n  hostname: argocd.example.test\n")
    (tmp_path / "addons-k3s.yaml").write_text("fixture")
    kubeconfig = tmp_path / "kubeconfig"
    kubeconfig.write_text("fixture")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("aws", "helm", "kubectl", "argocd", "curl"):
        command = bin_dir / name
        command.write_text(f"#!{sys.executable}\n{COMMAND}")
        command.chmod(0o755)
    log = tmp_path / "commands.jsonl"
    result = subprocess.run(
        ["bash", str(target / "install.sh")],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "COMMAND_LOG": str(log),
            "KUBECONFIG": str(kubeconfig),
            "FIXTURE_PASSWORD": PASSWORD,
            "SCENARIO": scenario,
            "FAIL_PARAMETER": parameter,
            "ARGOCD_READY_TIMEOUT": timeout,
        },
        capture_output=True, text=True, timeout=30,
    )
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    assert PASSWORD not in result.stdout + result.stderr
    return result, calls


@pytest.mark.parametrize("scenario", ["ssm_failure", "ssm_null", "ssm_empty"])
@pytest.mark.parametrize("parameter", ["admin-user", "admin-password", "argocd-password", "argocd-mtime"])
def test_invalid_ssm_values_stop_before_cluster_changes(tmp_path, scenario, parameter):
    result, calls = run_installer(tmp_path, scenario, parameter)
    assert result.returncode != 0
    assert calls
    assert all(call[0] == "aws" for call in calls)


def test_waits_for_gateway_certificate_before_login(tmp_path):
    result, calls = run_installer(tmp_path, "recover", parameter="unused")
    assert result.returncode == 0, result.stderr
    probes = [index for index, call in enumerate(calls) if call[0] == "curl"]
    assert len(probes) == 2
    login = next(call for call in calls if call[:2] == ["argocd", "login"])
    assert calls.index(login) > probes[-1]
    assert login[login.index("--password") + 1] == PASSWORD
    assert calls[probes[-1]][-1] == "https://argocd.example.test/healthz"


def test_readiness_timeout_stops_before_login(tmp_path):
    result, calls = run_installer(tmp_path, "timeout", parameter="unused", timeout="1")
    assert result.returncode != 0
    assert "1초 안에 준비되지 않았습니다" in result.stderr
    assert not any(call[0] == "argocd" for call in calls)


def test_login_failure_is_not_retried(tmp_path):
    result, calls = run_installer(tmp_path, "login_failure", parameter="unused")
    assert result.returncode == 20
    assert sum(call[:2] == ["argocd", "login"] for call in calls) == 1


def test_invalid_timeout_stops_before_external_calls(tmp_path):
    result, calls = run_installer(tmp_path, timeout="0")
    assert result.returncode != 0
    assert calls == []
