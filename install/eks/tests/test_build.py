import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml


INSTALL_DIR = Path(__file__).resolve().parents[1]
SECRET = 'fixture/secret & @ \\ " \'\nARGOCD_HOSTNAME GITHUB_ORG'

AWS = r'''
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
scenario = os.environ.get("SCENARIO", "ready")
if args[0] == "acm":
    if scenario == "acm_failure":
        sys.exit(254)
    certificates = [{"DomainName": "other-argocd.example.test", "CertificateArn": "arn:aws:acm:fixture:123:certificate/wrong-host"}]
    if scenario != "acm_missing":
        certificates.append({"DomainName": "argocd.example.test", "CertificateArn": "arn:aws:acm:fixture:123:certificate/fixture"})
    print(json.dumps({"CertificateSummaryList": certificates}))
    sys.exit()
parameter = args[args.index("--name") + 1].rsplit("/", 1)[-1]
values = json.loads(Path(os.environ["SSM_VALUES"]).read_text())
if parameter == "argocd-password":
    if scenario == "ssm_failure":
        print("AccessDeniedException", file=sys.stderr)
        sys.exit(254)
    if scenario == "invalid_json":
        print("not json")
        sys.exit()
    if scenario in ("null", "empty", "wrong_type"):
        values[parameter] = {"null": None, "empty": "", "wrong_type": 123}[scenario]
print(json.dumps({"Parameter": {"Value": values[parameter]}}))
'''


def run_build(tmp_path, scenario="ready"):
    target = tmp_path / "eks"
    target.mkdir()
    for name in ("build.py", "build.sh", "values.yaml"):
        shutil.copy2(INSTALL_DIR / name, target / name)
    output = target / "values.output.yaml"
    output.write_text("previous output\n")
    output.chmod(0o644)
    values = {
        "argocd-hostname": "argocd.example.test",
        "github-org": "fixture-org",
        "github-team": "fixture-team",
        "argocd-password": SECRET,
        "argocd-mtime": "2026-01-01T00:00:00Z",
        "argocd-server-secret": SECRET,
        "argocd-webhook": SECRET,
        "argocd-mcp-tokens": '[{"id":"fixture", "iat":123}]',
        "argocd-github-id": "123",
        "argocd-github-secret": SECRET,
    }
    values_path = tmp_path / "ssm.json"
    values_path.write_text(json.dumps(values))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    command = bin_dir / "aws"
    command.write_text(f"#!{sys.executable}\n{AWS}")
    command.chmod(0o755)
    result = subprocess.run(
        ["bash", str(target / "build.sh")],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{Path(sys.executable).parent}:{os.environ['PATH']}",
            "SSM_VALUES": str(values_path),
            "SCENARIO": scenario,
        },
        capture_output=True, text=True, timeout=15,
    )
    assert SECRET not in result.stdout + result.stderr
    return result, output, values


def test_build_preserves_secret_characters_and_writes_private_yaml(tmp_path):
    result, output, values = run_build(tmp_path)
    assert result.returncode == 0, result.stderr
    rendered = yaml.safe_load(output.read_text())
    secret = rendered["configs"]["secret"]
    assert secret["argocdServerAdminPassword"] == SECRET
    assert secret["githubSecret"] == SECRET
    assert secret["extra"]["server.secretkey"] == SECRET
    assert secret["extra"]["dex.github.clientSecret"] == SECRET
    assert secret["extra"]["accounts.mcp.tokens"] == values["argocd-mcp-tokens"]
    assert rendered["configs"]["cm"]["url"] == "https://argocd.example.test"
    assert rendered["server"]["ingress"]["annotations"]["alb.ingress.kubernetes.io/certificate-arn"] == "arn:aws:acm:fixture:123:certificate/fixture"
    assert "g, fixture-org:fixture-team, role:admin" in rendered["configs"]["rbac"]["policy.csv"]
    assert output.stat().st_mode & 0o777 == 0o600
    assert list(output.parent.glob(".values.output-*.tmp")) == []


@pytest.mark.parametrize("scenario", [
    "ssm_failure", "invalid_json", "null", "empty", "wrong_type", "acm_failure", "acm_missing",
])
def test_build_failure_preserves_existing_output(tmp_path, scenario):
    result, output, _ = run_build(tmp_path, scenario)
    assert result.returncode != 0
    assert output.read_text() == "previous output\n"
    assert "파일이 생성되었습니다" not in result.stdout
    assert list(output.parent.glob(".values.output-*.tmp")) == []
