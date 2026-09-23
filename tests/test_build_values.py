import os
from pathlib import Path
import shutil
import subprocess

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_build_only_renders_and_preserves_the_git_index(tmp_path):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "env").mkdir()
    chart = repo / "charts/example"
    (chart / "eks").mkdir(parents=True)
    for name in ("build.sh", "gen_values.py"):
        shutil.copy2(ROOT / "scripts" / name, repo / "scripts" / name)
    (repo / "env/eks-test.yaml").write_text("env: eks\ncluster: eks-test\nreplicas: 2\n")
    (chart / "values-template.yaml.j2").write_text("replicas: {{ replicas }}\n")
    (repo / "notes.txt").write_text("unrelated staged work\n")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "add", "notes.txt"], cwd=repo, check=True)

    result = subprocess.run(
        ["bash", str(repo / "scripts/build.sh")], cwd=tmp_path,
        env={**os.environ, "GITHUB_PUSH": "true"}, capture_output=True, text=True,
    )

    assert result.returncode == 0, result.stderr
    assert yaml.safe_load((chart / "eks/values-eks-test.yaml").read_text()) == {"replicas": 2}
    staged = subprocess.check_output(["git", "diff", "--cached", "--name-only"], cwd=repo, text=True)
    assert staged.splitlines() == ["notes.txt"]
    assert subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=repo, capture_output=True).returncode != 0
