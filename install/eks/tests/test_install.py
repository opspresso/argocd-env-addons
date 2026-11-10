import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


INSTALLER = Path(__file__).resolve().parents[1] / "install.sh"

# Only external commands and the SSM values generator are replaced. Bash's
# error handling, argument expansion, jq parsing and readiness deadline are real.
COMMAND = r'''
import json
import os
from pathlib import Path
import sys

name = Path(sys.argv[0]).name
args = sys.argv[1:]
log = Path(os.environ["COMMAND_LOG"])
with log.open("a") as stream:
    stream.write(json.dumps([name, *args]) + "\n")
scenario = os.environ.get("SCENARIO", "ready")

if name == "aws":
    # install.sh reads nothing from SSM itself: token.sh, secrets.sh and build.sh do.
    sys.exit(1)
elif name == "python3" and len(args) > 2 and "yaml.safe_load" in args[1]:
    if scenario == "env_invalid":
        sys.exit(1)
    print("argocd.example.test")
elif name == "helm" and args[0] == "upgrade" and scenario == "helm_failure":
    sys.exit(1)
elif name == "kubectl" and scenario == "kubectl_failure":
    sys.exit(1)
elif name == "python3" and scenario == "python_dependency_missing":
    sys.exit(1)
'''


class InstallTest(unittest.TestCase):
    def run_installer(self, scenario="ready"):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "install" / "eks"
            root.mkdir(parents=True)
            bin_dir = Path(directory) / "bin"
            bin_dir.mkdir()
            shutil.copy2(INSTALLER, root / "install.sh")
            for name in ("aws", "jq", "helm", "kubectl", "openssl", "uuidgen", "python3", "token.sh", "secrets.sh", "build.sh"):
                path = root / name if name.endswith(".sh") else bin_dir / name
                path.write_text(f"#!{sys.executable}\n{COMMAND}")
                path.chmod(0o755)
            # jq is real in the installer's ssm(); use the system jq when present.
            system_jq = shutil.which("jq")
            if system_jq:
                (bin_dir / "jq").unlink()
                (bin_dir / "jq").symlink_to(system_jq)
            log = Path(directory) / "commands.jsonl"
            result = subprocess.run(
                ["/bin/bash", str(root / "install.sh")],
                env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "COMMAND_LOG": str(log), "SCENARIO": scenario},
                capture_output=True, text=True, timeout=40,
            )
            commands = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return result, commands

    def test_registers_cluster_projects_addons_and_apps_without_public_access(self):
        result, commands = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        names = [command[0] for command in commands]
        self.assertNotIn("argocd", names)
        self.assertNotIn("curl", names)
        install = next(i for i, c in enumerate(commands) if c[:2] == ["helm", "upgrade"])
        applied = [c for c in commands if c[:2] == ["kubectl", "apply"]]
        self.assertEqual([c[-1] for c in applied], ["bootstrap.yaml", "../../addons-eks.yaml",
                         "https://raw.githubusercontent.com/opspresso/argocd-env-apps/main/apps-eks.yaml"])
        self.assertTrue(all(commands.index(c) > install for c in applied))
        self.assertIn("https://argocd.example.test", result.stdout)

    def test_creates_addon_secrets_before_values_and_installation(self):
        result, commands = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        names = [command[0] for command in commands]
        # argocd-secret reads the OIDC client secrets that secrets.sh creates.
        self.assertLess(names.index("token.sh"), names.index("secrets.sh"))
        self.assertLess(names.index("secrets.sh"), names.index("build.sh"))
        install = next(i for i, c in enumerate(commands) if c[:2] == ["helm", "upgrade"])
        self.assertLess(names.index("secrets.sh"), install)

    def test_reads_cluster_settings_from_env_not_ssm(self):
        result, commands = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(command[0] == "aws" for command in commands))
        read = next(c for c in commands if c[0] == "python3" and len(c) > 2 and "yaml.safe_load" in c[2])
        self.assertEqual(read[-1], "../../env/eks-demo.yaml")

    def test_invalid_env_stops_before_ssm_writes(self):
        result, commands = self.run_installer("env_invalid")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("클러스터 설정 확인 (env/eks-demo.yaml) 단계 실패", result.stderr)
        self.assertFalse(any(command[0] in ("token.sh", "secrets.sh", "build.sh", "kubectl") for command in commands))
        self.assertFalse(any(command[:2] == ["helm", "upgrade"] for command in commands))

    def test_helm_error_stops_before_registration(self):
        result, commands = self.run_installer("helm_failure")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Argo CD 설치 단계 실패", result.stderr)
        self.assertFalse(any(command[0] == "kubectl" for command in commands))

    def test_registration_error_stops_before_addons(self):
        result, commands = self.run_installer("kubectl_failure")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("클러스터·AppProject 등록 단계 실패", result.stderr)
        self.assertEqual(sum(command[0] == "kubectl" for command in commands), 1)

    def test_missing_python_dependency_stops_before_ssm_writes(self):
        result, commands = self.run_installer("python_dependency_missing")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("bcrypt·PyYAML이 필요합니다", result.stderr)
        self.assertEqual(commands, [["python3", "-c", "import bcrypt, yaml"]])


if __name__ == "__main__":
    unittest.main()
