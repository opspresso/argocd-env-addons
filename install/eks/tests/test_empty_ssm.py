"""The installer prepares every SSM value that the deployed addons read.

token.sh, secrets.sh and build.sh run in the installer's order against one
empty fake SSM. Every parameter that a deployed addon (addons/eks) references
must exist afterwards, except the values issued outside (README: External
values). A new addon that reads a parameter nobody creates fails here.
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
PARAMETER = re.compile(r"/k8s/[A-Za-z0-9_./-]+")

AWS = r'''
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
path = Path(os.environ["SSM_STATE"])
state = json.loads(path.read_text())
name = args[args.index("--name") + 1]
if args[1] == "get-parameter":
    if name not in state:
        print("An error occurred (ParameterNotFound) when calling the GetParameter operation: missing", file=sys.stderr)
        sys.exit(254)
    print(json.dumps({"Parameter": {"Value": state[name]}}))
elif args[1] == "put-parameter":
    if name in state and "--overwrite" not in args:
        print("An error occurred (ParameterAlreadyExists) when calling the PutParameter operation: exists", file=sys.stderr)
        sys.exit(254)
    state[name] = args[args.index("--value") + 1]
    path.write_text(json.dumps(state))
    print('{"Version": 1}')
'''


def deployed_parameters():
    names = set()
    for application in sorted((ROOT / "addons" / "eks").glob("*.yaml")):
        chart = ROOT / "charts" / application.stem
        for values in (chart / "values.yaml", chart / "eks" / "values-eks-demo.yaml"):
            if values.exists():
                # Commented lines are switched-off features (the GitHub sign-in).
                text = "\n".join(line for line in values.read_text().splitlines()
                                 if not line.lstrip().startswith("#"))
                names.update(PARAMETER.findall(text))
    return names


def test_empty_ssm_ends_with_every_parameter_the_addons_read(tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(INSTALL_DIR, repo / "install" / "eks", ignore=shutil.ignore_patterns("tests", "__pycache__", "values.output.yaml"))
    shutil.copytree(ROOT / "env", repo / "env")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "aws").write_text(f"#!{sys.executable}\n{AWS}")
    (bin_dir / "aws").chmod(0o755)
    state = tmp_path / "ssm.json"
    state.write_text("{}")
    env = {**os.environ, "PATH": f"{bin_dir}:{Path(sys.executable).parent}:{os.environ['PATH']}", "SSM_STATE": str(state)}

    for command in (["./token.sh"], ["./token.sh", "--account", "keep"], ["./secrets.sh"], ["./build.sh"]):
        result = subprocess.run(["/bin/bash", *command], cwd=repo / "install" / "eks", env=env,
                                capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, (command, result.stdout, result.stderr)

    created = set(json.loads(state.read_text()))
    referenced = deployed_parameters()
    assert len(referenced) > 20, sorted(referenced)
    missing = referenced - created - EXTERNAL
    assert not missing, f"no installer step creates: {sorted(missing)}"
    assert not EXTERNAL & created
    assert (repo / "install" / "eks" / "values.output.yaml").exists()
