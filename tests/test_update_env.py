import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
AWS = r'''
import os
import sys

args = sys.argv[1:]
scenario = os.environ.get("SCENARIO", "ready")
if args[:2] == ["sts", "get-caller-identity"]:
    print("123456789012")
elif args[:2] == ["ec2", "describe-vpcs"]:
    assert "Name=tag:Name,Values=vpc-demo" in args, args
    print("None" if scenario == "missing_vpc" else "vpc-current")
elif args[:2] == ["acm", "list-certificates"]:
    if scenario in ("shared_cert", "special_cert"):
        certificate = r"arn:argocd$new\certificate|new" if scenario == "special_cert" else "arn:argocd-new"
        print("argocd.demo.opspresso.com\t" + certificate)
        print("demo.opspresso.com\tarn:atlantis-new")
elif args[:2] == ["elbv2", "describe-target-groups"]:
    name = args[args.index("--names") + 1]
    assert name in ("demo-h1-0", "demo-in-http-0", "demo-grpc-0"), args
    if scenario == "denied":
        print("AccessDenied", file=sys.stderr)
        sys.exit(254)
    print("arn:aws:elasticloadbalancing:region:123456789012:targetgroup/" + name + "/current")
else:
    raise AssertionError(args)
'''


class UpdateEnvTest(unittest.TestCase):
    def run_update(self, scenario="ready", environment=True):
        with tempfile.TemporaryDirectory(prefix="update env ") as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            shutil.copy2(ROOT / "scripts/update_env.sh", root / "scripts/update_env.sh")
            (root / "env").mkdir()
            config = (ROOT / "env/eks-demo.yaml").read_text()
            config = config.replace('aws_account_id: "396608815058"', 'aws_account_id: "123456789012"')
            if scenario in ("shared_cert", "special_cert"):
                previous = yaml.safe_load(config)
                shared = r"arn:shared$old\certificate|old"
                for key in ("argocd", "atlantis"):
                    config = config.replace(previous[key]["acm_arn"], shared)
                config += f"\n# Keep this reference: {shared}\ncertificate_note: {shared}\n"
            if not environment:
                config = config.replace("aws_environment: demo\n", "")
            target = root / "env/eks-demo.yaml"
            target.write_text(config)
            (root / "bin").mkdir()
            aws = root / "bin/aws"
            aws.write_text(f"#!{sys.executable}\n{AWS}")
            aws.chmod(0o755)
            env = dict(os.environ, PATH=f"{root / 'bin'}:{os.environ['PATH']}", SCENARIO=scenario)
            result = subprocess.run(["bash", str(root / "scripts/update_env.sh")], env=env, capture_output=True, text=True)
            self.assertEqual(list((root / "env").glob("*.tmp.*")), [])
            return result, target.read_text(), config

    def test_platform_is_distinct_from_aws_environment(self):
        result, updated, _ = self.run_update()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("vpcId: vpc-current", updated)
        for name in ("demo-h1-0", "demo-in-http-0", "demo-grpc-0"):
            self.assertIn(f"targetgroup/{name}/current", updated)

    def test_missing_environment_fails_without_changes(self):
        result, updated, original = self.run_update(environment=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("aws_environment is required", result.stderr)
        self.assertEqual(updated, original)

    def test_missing_vpc_fails_without_changes(self):
        result, updated, original = self.run_update("missing_vpc")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("VPC vpc-demo not found", result.stderr)
        self.assertEqual(updated, original)

    def test_target_group_lookup_failure_is_not_hidden(self):
        result, updated, original = self.run_update("denied")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("AccessDenied", result.stderr)
        self.assertNotIn("Done.", result.stdout)
        self.assertEqual(updated, original)

    def test_shared_old_values_only_update_the_requested_keys(self):
        result, updated, original = self.run_update("shared_cert")
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = yaml.safe_load(updated)
        self.assertEqual(parsed["argocd"]["acm_arn"], "arn:argocd-new")
        self.assertEqual(parsed["atlantis"]["acm_arn"], "arn:atlantis-new")
        self.assertEqual(parsed["certificate_note"], yaml.safe_load(original)["certificate_note"])
        self.assertIn(r"# Keep this reference: arn:shared$old\certificate|old", updated)

    def test_replacement_characters_are_written_as_literal_values(self):
        result, updated, _ = self.run_update("special_cert")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(yaml.safe_load(updated)["argocd"]["acm_arn"], r"arn:argocd$new\certificate|new")
