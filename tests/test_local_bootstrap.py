import os
import re
import shlex
import shutil
from pathlib import Path
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("context", ["orbstack", "docker-desktop"])
def test_existing_argocd_is_reused_without_reinstalling_or_reading_credentials(tmp_path, context):
    log = tmp_path / "commands"
    for name in ("kubectl", "helm", "aws"):
        executable = tmp_path / name
        executable.write_text(f'#!/bin/sh\nprintf "%s\\n" "{name} $*" >> "$COMMAND_LOG"\n')
        if name == "helm":
            executable.write_text(executable.read_text() + 'case "$*" in *" get manifest "*) printf "kind: ConfigMap\\nmetadata: {name: fixture}\\n" ;; *) printf "argocd\\n" ;; esac\n')
        executable.chmod(0o755)
    subprocess.run(
        ["bash", str(ROOT / "install/local/install.sh")], check=True, capture_output=True, text=True,
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "COMMAND_LOG": str(log), "KUBE_CONTEXT": context},
    )
    commands = log.read_text()
    assert f"helm --kube-context {context} list --deployed --failed --pending --uninstalling --namespace argocd --filter ^argocd$ -q" in commands
    assert f"kubectl --context {context} get nodes" in commands
    assert "upgrade" not in commands
    assert "aws " not in commands
    assert "install/local/projects.yaml" in commands
    assert "addons-local.yaml" in commands
    assert "apps-local.yaml" in commands
    assert commands.index("--for=condition=Ready clustersecretstore/parameter-store") < commands.index("apps-local.yaml")


def test_local_gitops_uses_existing_controller_and_scoped_projects():
    root = yaml.safe_load((ROOT / "addons-local.yaml").read_text())
    assert root["metadata"]["namespace"] == root["spec"]["destination"]["namespace"] == "argocd"
    assert root["spec"]["project"] == "addons"
    assert not (ROOT / "addons/local/argo-cd.yaml").exists()
    projects = {doc["metadata"]["name"]: doc for doc in yaml.safe_load_all((ROOT / "install/local/projects.yaml").read_text())}
    for path in (ROOT / "addons/local").glob("*.yaml"):
        application = yaml.safe_load(path.read_text())
        assert application["metadata"]["namespace"] == "argocd"
        spec = application["spec"]
        project = projects[spec["project"]]["spec"]
        assert spec["destination"] in project["destinations"]
        assert spec["source"]["repoURL"] in project["sourceRepos"]


def test_installer_lookup_flags_are_supported_by_installed_helm():
    if not shutil.which("helm"):
        pytest.skip("Helm is required to validate CLI compatibility")
    script = (ROOT / "install/local/install.sh").read_text()
    lookup = re.search(r"EXISTING_RELEASE=\$\(run_helm (.+)\)", script)
    assert lookup
    result = subprocess.run(["helm", *shlex.split(lookup.group(1)), "--help"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
