"""The installer prepares every Secrets Manager secret that the deployed addons read.

token.sh, secrets.sh and build.sh run in the installer's order against one
empty fake Secrets Manager. Every secret that a deployed addon (addons/eks)
references must exist afterwards, except the values issued outside (README:
External values). A new addon that reads a secret nobody creates fails here.
"""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


INSTALL_DIR = Path(__file__).resolve().parents[1]
ROOT = INSTALL_DIR.parents[1]
# Issued outside: secrets.sh only reports them (README 'External values').
EXTERNAL = {
    "/k8s/common/github/opspresso-arc/app_id",
    "/k8s/common/github/opspresso-arc/installation_id",
    "/k8s/common/github/opspresso-arc/private_key",
    "/k8s/common/keep/slack-bot-token",
}
SECRET_NAME = re.compile(r"/k8s/[A-Za-z0-9_./-]+")

AWS = r'''
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
path = Path(os.environ["SECRETS_STATE"])
state = json.loads(path.read_text())
operation = args[1]
name = args[args.index("--name" if operation == "create-secret" else "--secret-id") + 1]
action = {
    "describe-secret": "DescribeSecret", "get-secret-value": "GetSecretValue",
    "create-secret": "CreateSecret", "put-secret-value": "PutSecretValue",
}[operation]
if operation == "create-secret":
    if name in state:
        print(f"An error occurred (ResourceExistsException) when calling the {action} operation: exists", file=sys.stderr)
        sys.exit(254)
elif name not in state:
    print(f"An error occurred (ResourceNotFoundException) when calling the {action} operation: missing", file=sys.stderr)
    sys.exit(254)
if operation == "describe-secret":
    print(json.dumps({"Name": name}))
elif operation == "get-secret-value":
    print(json.dumps({"Name": name, "SecretString": state[name], "VersionId": "v1"}))
else:
    state[name] = args[args.index("--secret-string") + 1]
    path.write_text(json.dumps(state))
    print(json.dumps({"Name": name, "VersionId": "v1"}))
'''


def deployed_secrets():
    names = set()
    for application in sorted((ROOT / "addons" / "eks").glob("*.yaml")):
        chart = ROOT / "charts" / application.stem
        for values in (chart / "values.yaml", chart / "eks" / "values-eks-demo.yaml"):
            if values.exists():
                # Commented lines are switched-off features (the GitHub sign-in).
                text = "\n".join(line for line in values.read_text().splitlines()
                                 if not line.lstrip().startswith("#"))
                names.update(SECRET_NAME.findall(text))
    return names


def test_empty_store_ends_with_every_secret_the_addons_read(tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(INSTALL_DIR, repo / "install" / "eks", ignore=shutil.ignore_patterns("tests", "__pycache__", "values.output.yaml"))
    shutil.copytree(ROOT / "env", repo / "env")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "aws").write_text(f"#!{sys.executable}\n{AWS}")
    (bin_dir / "aws").chmod(0o755)
    state = tmp_path / "secrets.json"
    state.write_text("{}")
    env = {**os.environ, "PATH": f"{bin_dir}:{Path(sys.executable).parent}:{os.environ['PATH']}", "SECRETS_STATE": str(state)}

    for command in (["./token.sh"], ["./token.sh", "--account", "keep"], ["./secrets.sh"], ["./build.sh"]):
        result = subprocess.run(["/bin/bash", *command], cwd=repo / "install" / "eks", env=env,
                                capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, (command, result.stdout, result.stderr)

    created = set(json.loads(state.read_text()))
    referenced = deployed_secrets()
    assert len(referenced) > 20, sorted(referenced)
    missing = referenced - created - EXTERNAL
    assert not missing, f"no installer step creates: {sorted(missing)}"
    assert not EXTERNAL & created
    assert (repo / "install" / "eks" / "values.output.yaml").exists()
