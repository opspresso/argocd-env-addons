import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


SCRIPT = Path(__file__).resolve().parents[1] / "kanidm.sh"
ENV = Path(__file__).resolve().parents[3] / "env" / "eks-demo.yaml"
ADMIN = "/k8s/common/kanidm/idm-admin-password"
CLIENT = "/k8s/common/kanidm/dex-client-secret"

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
with (root / "calls.jsonl").open("a") as stream:
    stream.write(json.dumps(["aws", args[1], name]) + "\n")
if args[1] == "get-parameter":
    if name not in state:
        print("An error occurred (ParameterNotFound) when calling the GetParameter operation: missing", file=sys.stderr)
        sys.exit(254)
    print(json.dumps({"Parameter": {"Value": state[name]}}))
else:
    state[name] = args[args.index("--value") + 1]
    state_path.write_text(json.dumps(state))
    print('{"Version": 2}')
'''

# Kanidm: the admin password that logs in is in kanidm.json; recover-account
# replaces it. The password reaches `kubectl run` on standard input only.
KUBECTL = r'''
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
root = Path(os.environ["FIXTURE_ROOT"])
kanidm_path = root / "kanidm.json"
kanidm = json.loads(kanidm_path.read_text())
with (root / "calls.jsonl").open("a") as stream:
    stream.write(json.dumps(["kubectl", *args]) + "\n")
if "run" in args:
    if any(kanidm["admin"] in arg for arg in args):
        sys.exit(90)  # the password must not appear in the Pod spec
    password = sys.stdin.readline().rstrip("\n")
    if password != kanidm["admin"]:
        sys.exit(1)
    if "show-basic-secret" in args[-1]:
        print(kanidm["client"])
elif "exec" in args:
    kanidm["admin"] = "recovered-password"
    kanidm_path.write_text(json.dumps(kanidm))
    print('INFO  [info]:  | new_password: "recovered-password"')
'''


def run(tmp_path, ssm, kanidm):
    root = tmp_path / "repo"
    (root / "install" / "eks").mkdir(parents=True)
    (root / "env").mkdir()
    shutil.copy2(SCRIPT, root / "install" / "eks" / "kanidm.sh")
    shutil.copy2(ENV, root / "env" / "eks-demo.yaml")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("aws", AWS), ("kubectl", KUBECTL)):
        path = bin_dir / name
        path.write_text(f"#!{sys.executable}\n{body}")
        path.chmod(0o755)
    (tmp_path / "ssm.json").write_text(json.dumps(ssm))
    (tmp_path / "kanidm.json").write_text(json.dumps(kanidm))
    result = subprocess.run(
        ["/bin/bash", str(root / "install" / "eks" / "kanidm.sh")],
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "FIXTURE_ROOT": str(tmp_path)},
        capture_output=True, text=True, timeout=60,
    )
    calls = [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]
    return result, json.loads((tmp_path / "ssm.json").read_text()), calls


def puts(calls):
    return [c[2] for c in calls if c[:2] == ["aws", "put-parameter"]]


def test_valid_values_change_nothing(tmp_path):
    result, ssm, calls = run(tmp_path, {ADMIN: "admin-pw", CLIENT: "client-secret"},
                             {"admin": "admin-pw", "client": "client-secret"})
    assert result.returncode == 0, result.stderr
    assert puts(calls) == []
    assert not any("exec" in c or "restart" in c for c in calls)


def test_missing_admin_password_is_recovered_stored_and_synced(tmp_path):
    result, ssm, calls = run(tmp_path, {CLIENT: "client-secret"}, {"admin": "unknown", "client": "client-secret"})
    assert result.returncode == 0, result.stderr
    assert ssm[ADMIN] == "recovered-password"
    assert puts(calls) == [ADMIN]
    assert any(c[:1] == ["kubectl"] and "annotate" in c and "kanidm-idm-admin" in c for c in calls)
    assert "recovered-password" not in result.stdout + result.stderr


def test_stale_admin_password_is_replaced(tmp_path):
    result, ssm, _ = run(tmp_path, {ADMIN: "old", CLIENT: "client-secret"}, {"admin": "current", "client": "client-secret"})
    assert result.returncode == 0, result.stderr
    assert ssm[ADMIN] == "recovered-password"


def test_changed_client_secret_is_stored_and_dex_restarted(tmp_path):
    result, ssm, calls = run(tmp_path, {ADMIN: "admin-pw", CLIENT: "old"}, {"admin": "admin-pw", "client": "new-secret"})
    assert result.returncode == 0, result.stderr
    assert ssm[CLIENT] == "new-secret"
    restart = next(i for i, c in enumerate(calls) if "restart" in c)
    sync = next(i for i, c in enumerate(calls) if "annotate" in c and "argocd-secret" in c)
    assert sync < restart
    assert "new-secret" not in result.stdout + result.stderr


def test_missing_oauth2_client_stops_without_writing(tmp_path):
    result, ssm, calls = run(tmp_path, {ADMIN: "admin-pw"}, {"admin": "admin-pw", "client": ""})
    assert result.returncode == 1
    assert "provisioning Job" in result.stderr
    assert puts(calls) == []
