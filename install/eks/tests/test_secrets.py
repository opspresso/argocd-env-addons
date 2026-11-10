import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "secrets.sh"

# Fake aws keeps SSM in a JSON file. openssl and bash are real, so the
# generated values are what the script really makes.
AWS = r'''
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
root = Path(os.environ["FIXTURE_ROOT"])
state_path = root / "ssm.json"
state = json.loads(state_path.read_text())
name = args[args.index("--name") + 1]
operation = args[1]
with (root / "calls.jsonl").open("a") as stream:
    stream.write(json.dumps([operation, name, "--overwrite" in args]) + "\n")
if operation == "get-parameter":
    if name == os.environ.get("DENY_PARAMETER"):
        print("An error occurred (AccessDeniedException) when calling the GetParameter operation: denied", file=sys.stderr)
        sys.exit(254)
    if name not in state:
        print("An error occurred (ParameterNotFound) when calling the GetParameter operation: missing", file=sys.stderr)
        sys.exit(254)
    print(json.dumps({"Parameter": {"Value": state[name]}}))
elif operation == "put-parameter":
    if name == os.environ.get("RACE_PARAMETER"):
        state[name] = "created-by-another-installer"
        state_path.write_text(json.dumps(state))
    if name in state and "--overwrite" not in args:
        print("An error occurred (ParameterAlreadyExists) when calling the PutParameter operation: exists", file=sys.stderr)
        sys.exit(254)
    value = args[args.index("--value") + 1]
    if value.startswith("file://"):
        value = Path(value[len("file://"):]).read_text()
    state[name] = value
    state_path.write_text(json.dumps(state))
    print('{"Version": 1}')
'''


def run(tmp_path, state, *args, **env):
    root = tmp_path / "repo"
    (root / "install" / "eks").mkdir(parents=True)
    shutil.copy2(SCRIPT, root / "install" / "eks" / "secrets.sh")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    aws = bin_dir / "aws"
    aws.write_text(f"#!{sys.executable}\n{AWS}")
    aws.chmod(0o755)
    (tmp_path / "ssm.json").write_text(json.dumps(state))
    result = subprocess.run(
        ["/bin/bash", str(root / "install" / "eks" / "secrets.sh"), *args],
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "FIXTURE_ROOT": str(tmp_path), **env},
        capture_output=True, text=True, timeout=60,
    )
    calls = [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()] \
        if (tmp_path / "calls.jsonl").exists() else []
    return result, json.loads((tmp_path / "ssm.json").read_text()), calls


def test_creates_every_missing_secret_and_never_overwrites(tmp_path):
    result, state, calls = run(tmp_path, {"/k8s/common/gitlab/root-password": "kept"})
    assert result.returncode == 0, result.stderr
    assert state["/k8s/common/gitlab/root-password"] == "kept"
    assert not any(overwrite for _, _, overwrite in calls)
    for name in ("grafana", "gitlab", "jenkins", "keep"):
        assert len(state[f"/k8s/common/{name}/oidc-client-secret"]) == 32
    # Values must not leak to the output.
    assert state["/k8s/common/gitlab/postgres-password"] not in result.stdout


def test_check_reports_missing_parameters_without_writing(tmp_path):
    result, state, calls = run(tmp_path, {}, "--check")
    assert result.returncode == 1
    assert state == {}
    assert not any(op == "put-parameter" for op, _, _ in calls)
    assert "miss /k8s/common/gitlab/root-password" in result.stdout


def test_access_error_stops_before_any_write(tmp_path):
    result, state, calls = run(tmp_path, {}, DENY_PARAMETER="/k8s/common/grafana/oidc-client-secret")
    assert result.returncode != 0
    assert "SSM 조회 실패" in result.stderr
    assert state == {}


def test_value_created_by_another_installer_is_kept(tmp_path):
    result, state, _ = run(tmp_path, {}, RACE_PARAMETER="/k8s/common/nexus/admin-password")
    assert result.returncode == 0, result.stderr
    assert state["/k8s/common/nexus/admin-password"] == "created-by-another-installer"


@pytest.mark.parametrize("argument", ["--rotate", "extra"])
def test_unknown_argument_is_rejected(tmp_path, argument):
    result, _, calls = run(tmp_path, {}, argument)
    assert result.returncode == 2
    assert calls == []
