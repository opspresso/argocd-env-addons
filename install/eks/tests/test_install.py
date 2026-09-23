import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


INSTALLER = Path(__file__).resolve().parents[1] / "install.sh"
PASSWORD = "fixture password * [abc] $value"

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
previous = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
with log.open("a") as stream:
    stream.write(json.dumps([name, *args]) + "\n")
scenario = os.environ.get("SCENARIO", "ready")

if name == "aws":
    if scenario == "ssm_failure":
        print("AccessDeniedException", file=sys.stderr)
        sys.exit(254)
    parameter = args[args.index("--name") + 1].rsplit("/", 1)[-1]
    values = {
        "argocd-hostname": "argocd.example.test",
        "admin-user": "admin",
        "admin-password": os.environ["FIXTURE_PASSWORD"],
    }
    value = None if scenario == "ssm_empty" else values[parameter]
    print(json.dumps({"Parameter": {"Value": value}}))
elif name == "helm" and args[0] == "upgrade" and scenario == "helm_failure":
    sys.exit(1)
elif name == "curl":
    count = sum(command[0] == "curl" for command in previous)
    if scenario == "timeout":
        print("503", end="")
    elif scenario == "recover" and count == 0:
        print("000", end="")
        sys.exit(6)
    elif scenario == "recover" and count == 1:
        print("503", end="")
    else:
        print("200", end="")
elif name == "argocd" and args[0] == "login" and scenario == "login_failure":
    sys.exit(20)
elif name == "python3" and scenario == "python_dependency_missing":
    sys.exit(1)
'''


class InstallTest(unittest.TestCase):
    def run_installer(self, scenario="ready", timeout="30"):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            shutil.copy2(INSTALLER, root / "install.sh")
            for name in ("aws", "helm", "kubectl", "argocd", "curl", "openssl", "uuidgen", "python3", "token.sh", "build.sh"):
                path = root / name if name.endswith(".sh") else bin_dir / name
                path.write_text(f"#!{sys.executable}\n{COMMAND}")
                path.chmod(0o755)
            log = root / "commands.jsonl"
            result = subprocess.run(
                ["/bin/bash", str(root / "install.sh")],
                env={
                    **os.environ,
                    "PATH": f"{bin_dir}:{os.environ['PATH']}",
                    "COMMAND_LOG": str(log),
                    "FIXTURE_PASSWORD": PASSWORD,
                    "SCENARIO": scenario,
                    "ARGOCD_READY_TIMEOUT": timeout,
                },
                capture_output=True, text=True, timeout=40,
            )
            commands = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        self.assertNotIn(PASSWORD, result.stdout + result.stderr)
        return result, commands

    def test_waits_through_dns_failure_and_503_before_login(self):
        result, commands = self.run_installer("recover")
        self.assertEqual(result.returncode, 0, result.stderr)
        probes = [index for index, command in enumerate(commands) if command[0] == "curl"]
        self.assertEqual(len(probes), 3)
        login = next(command for command in commands if command[:2] == ["argocd", "login"])
        self.assertGreater(commands.index(login), probes[-1])
        self.assertEqual(login[2], "argocd.example.test")
        self.assertEqual(login[login.index("--password") + 1], PASSWORD)
        self.assertEqual(commands[probes[-1]][-1], "https://argocd.example.test/healthz")
        self.assertTrue(any(command[:3] == ["argocd", "cluster", "add"] for command in commands))

    def test_timeout_stops_before_login_and_cluster_registration(self):
        result, commands = self.run_installer("timeout", timeout="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("1초 안에 준비되지 않았습니다", result.stderr)
        self.assertFalse(any(command[0] == "argocd" for command in commands))

    def test_ssm_error_or_missing_value_stops_before_installation(self):
        for scenario in ("ssm_failure", "ssm_empty"):
            with self.subTest(scenario=scenario):
                result, commands = self.run_installer(scenario)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("SSM 접속 정보 조회 단계 실패", result.stderr)
                self.assertFalse(any(command[0] in ("token.sh", "build.sh", "kubectl", "argocd") for command in commands))
                self.assertFalse(any(command[:2] == ["helm", "upgrade"] for command in commands))

    def test_helm_error_stops_before_readiness_check(self):
        result, commands = self.run_installer("helm_failure")
        self.assertEqual(result.returncode, 1)
        self.assertIn("external-dns 설치 단계 실패", result.stderr)
        self.assertFalse(any(command[0] in ("curl", "argocd") for command in commands))

    def test_login_failure_is_not_retried_or_exposed(self):
        result, commands = self.run_installer("login_failure")
        self.assertEqual(result.returncode, 20)
        self.assertIn("Argo CD 로그인 단계 실패", result.stderr)
        self.assertEqual(sum(command[:2] == ["argocd", "login"] for command in commands), 1)
        self.assertFalse(any(command[:2] == ["argocd", "cluster"] for command in commands))

    def test_invalid_timeout_fails_before_external_commands(self):
        result, commands = self.run_installer(timeout="0")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(commands, [])

    def test_missing_python_dependency_stops_before_ssm_writes(self):
        result, commands = self.run_installer("python_dependency_missing")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PyYAML이 필요합니다", result.stderr)
        self.assertEqual(commands, [["python3", "-c", "import yaml"]])


if __name__ == "__main__":
    unittest.main()
