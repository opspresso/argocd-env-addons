from pathlib import Path
import unittest

from jinja2 import Environment, FileSystemLoader
import yaml

from gen_values import to_yaml


ROOT = Path(__file__).resolve().parents[1]


class LocalAWSTests(unittest.TestCase):
    def test_stores_use_the_default_sdk_chain_on_every_platform(self):
        environment = Environment(loader=FileSystemLoader(ROOT / "charts/external-secrets"))
        environment.filters["to_yaml"] = to_yaml
        template = environment.get_template("values-template.yaml.j2")
        for path in (ROOT / "env").glob("*.yaml"):
            context = yaml.safe_load(path.read_text())
            if context["env"] != "orb":
                context["aws_local"] = {"profile": "unused", "config_file": "/unused/config", "credentials_file": "/unused/credentials"}
            values = yaml.safe_load(template.render(context))
            with self.subTest(cluster=context["cluster"]):
                for store in values["raw"]["resources"]:
                    self.assertNotIn("auth", store["spec"]["provider"]["aws"])
                controller = values["external-secrets"]
                if context["env"] != "orb":
                    self.assertNotIn("extraVolumes", controller)
                    continue
                local = context["aws_local"]
                variables = {entry["name"]: entry["value"] for entry in controller["extraEnv"]}
                self.assertEqual(variables["AWS_PROFILE"], local["profile"])
                self.assertEqual(variables["AWS_CONFIG_FILE"], "/aws/config")
                self.assertEqual(variables["AWS_SHARED_CREDENTIALS_FILE"], "/aws/credentials")
                mounts = {entry["name"]: entry for entry in controller["extraVolumeMounts"]}
                paths = {entry["hostPath"]["path"] for entry in controller["extraVolumes"]}
                self.assertEqual(paths, {local["config_file"], local["credentials_file"]})
                for volume in controller["extraVolumes"]:
                    self.assertEqual(volume["hostPath"]["type"], "File")
                    self.assertTrue(mounts[volume["name"]]["readOnly"])
                self.assertNotIn("securityContext", controller)
                self.assertNotIn("extraVolumes", controller["webhook"])
                self.assertNotIn("extraVolumes", controller["certController"])

    def test_bootstrap_does_not_export_or_copy_aws_keys(self):
        script = (ROOT / "install/orb/install.sh").read_text()
        self.assertNotIn("configure export-credentials", script)
        self.assertNotIn("create secret generic", script)
        self.assertNotIn("AWS_ACCESS_KEY_ID", script)
        self.assertIn("aws ssm get-parameter", script)


if __name__ == "__main__":
    unittest.main()
