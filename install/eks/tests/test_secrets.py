import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import bcrypt
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
    tmp_path.mkdir(parents=True, exist_ok=True)
    root = tmp_path / "repo"
    (root / "install" / "eks").mkdir(parents=True)
    shutil.copy2(SCRIPT, root / "install" / "eks" / "secrets.sh")
    (root / "env").mkdir()
    (root / "env" / "eks-demo.yaml").write_text("argocd:\n  github:\n    org: fixture-org\n")
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


# Every value the installer needs and can make, in an empty SSM.
GENERATED = [
    "/k8s/common/admin-user", "/k8s/common/admin-password", "/k8s/common/argocd-password",
    "/k8s/common/argocd-mtime", "/k8s/common/argocd-webhook",
    "/k8s/common/argo-workflows-client-secret", "/k8s/common/oauth2-proxy-client-secret",
    "/k8s/common/cookie-secret", "/k8s/common/lldap/jwt-secret", "/k8s/common/lldap/key-seed",
    "/k8s/common/gitlab/root-password", "/k8s/common/keep/nextauth-secret",
]
EXTERNAL = [
    "/k8s/fixture-org/argocd-github-id", "/k8s/fixture-org/argocd-github-secret",
    "/k8s/common/github/opspresso-arc/app_id", "/k8s/common/github/opspresso-arc/installation_id",
    "/k8s/common/github/opspresso-arc/private_key", "/k8s/common/keep/slack-bot-token",
]


def hash_of(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(4)).decode()


def test_empty_ssm_gets_every_generated_value(tmp_path):
    result, state, calls = run(tmp_path, {})
    assert result.returncode == 0, result.stderr
    for name in GENERATED:
        assert state.get(name), name
    assert state["/k8s/common/admin-user"] == "admin"
    assert len(state["/k8s/common/cookie-secret"]) == 32
    # Argo CD reads the bcrypt hash of the same admin password as LLDAP and Grafana.
    password, digest = state["/k8s/common/admin-password"], state["/k8s/common/argocd-password"]
    assert digest.startswith("$2a$10$")
    assert bcrypt.checkpw(password.encode(), digest.encode())
    assert not any(overwrite for _, _, overwrite in calls)
    # Values issued outside are not made up; each missing one is reported.
    for name in EXTERNAL:
        assert name not in state
        assert f"warn {name} 없음" in result.stdout
    assert password not in result.stdout + result.stderr


def test_existing_ssm_is_kept_unchanged(tmp_path):
    existing = {name: f"kept-{index}" for index, name in enumerate(GENERATED)}
    existing["/k8s/common/admin-password"] = "chosen password"
    existing["/k8s/common/argocd-password"] = hash_of("chosen password")
    for name in EXTERNAL:
        existing[name] = "issued"
    result, state, calls = run(tmp_path, existing)
    assert result.returncode == 0, result.stderr
    for name, value in existing.items():
        assert state[name] == value, name
    assert not any(overwrite for _, _, overwrite in calls)
    assert "warn" not in result.stdout


def test_argocd_password_follows_a_changed_admin_password(tmp_path):
    existing = {
        "/k8s/common/admin-password": "new password",
        "/k8s/common/argocd-password": hash_of("old password"),
        "/k8s/common/argocd-mtime": "2026-01-01T00:00:00Z",
    }
    result, state, calls = run(tmp_path, existing)
    assert result.returncode == 0, result.stderr
    assert bcrypt.checkpw(b"new password", state["/k8s/common/argocd-password"].encode())
    assert state["/k8s/common/argocd-mtime"] != "2026-01-01T00:00:00Z"
    assert state["/k8s/common/admin-password"] == "new password"
    overwritten = {name for _, name, overwrite in calls if overwrite}
    assert overwritten == {"/k8s/common/argocd-password", "/k8s/common/argocd-mtime"}


def test_check_reports_a_stale_argocd_password_without_writing(tmp_path):
    existing = {
        "/k8s/common/admin-password": "new password",
        "/k8s/common/argocd-password": hash_of("old password"),
    }
    result, state, calls = run(tmp_path, existing, "--check")
    assert result.returncode == 1
    assert state == existing
    assert not any(op == "put-parameter" for op, _, _ in calls)
    assert "miss /k8s/common/argocd-password (다시 만들어야 합니다)" in result.stdout


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
    result, state, calls = run(tmp_path, {}, DENY_PARAMETER="/k8s/common/admin-user")
    assert result.returncode != 0
    assert "SSM 조회 실패" in result.stderr
    assert state == {}


def test_access_error_stops_and_a_rerun_completes(tmp_path):
    result, state, _ = run(tmp_path, {}, DENY_PARAMETER="/k8s/common/grafana/oidc-client-secret")
    assert result.returncode != 0
    assert "SSM 조회 실패" in result.stderr
    assert "/k8s/common/grafana/oidc-client-secret" not in state
    # Values made before the error stay; the next run keeps them and adds the rest.
    created = dict(state)
    result, state, _ = run(tmp_path / "rerun", created)
    assert result.returncode == 0, result.stderr
    assert all(state[name] == value for name, value in created.items())
    assert state["/k8s/common/grafana/oidc-client-secret"]


def test_value_created_by_another_installer_is_kept(tmp_path):
    result, state, _ = run(tmp_path, {}, RACE_PARAMETER="/k8s/common/nexus/admin-password")
    assert result.returncode == 0, result.stderr
    assert state["/k8s/common/nexus/admin-password"] == "created-by-another-installer"


@pytest.mark.parametrize("argument", ["--rotate", "extra"])
def test_unknown_argument_is_rejected(tmp_path, argument):
    result, _, calls = run(tmp_path, {}, argument)
    assert result.returncode == 2
    assert calls == []
