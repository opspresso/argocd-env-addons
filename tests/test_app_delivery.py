from pathlib import Path
import re
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
# Agent Runway DELIVERY_ENVIRONMENTS name rule (agent-platform docs/DELIVERY_V2.md D1).
ENVIRONMENT_NAME = re.compile(r"^[a-z][a-z0-9]{1,11}$")


def rendered_values(cluster):
    for path in (ROOT / "charts/argo-cd").glob(f"*/values-{cluster}.yaml"):
        return yaml.safe_load(path.read_text())
    raise AssertionError(f"no rendered argo-cd values for {cluster}")


def resource(values, kind, name):
    return next(r for r in values["raw"]["resources"] if r["kind"] == kind and r["metadata"]["name"] == name)


class AppDeliveryProfileTests(unittest.TestCase):
    def contexts(self):
        for path in sorted((ROOT / "env").glob("*.yaml")):
            context = yaml.safe_load(path.read_text())
            if context.get("app_delivery", {}).get("enabled"):
                yield context

    def test_tenant_apps_may_create_only_the_app_kinds_and_platform_resources(self):
        for context in self.contexts():
            values = rendered_values(context["cluster"])
            project = resource(values, "AppProject", "projects")
            with self.subTest(cluster=context["cluster"]):
                kinds = {(k["group"], k["kind"]) for k in project["spec"]["namespaceResourceWhitelist"]}
                for kind in ("RdsPostgres", "S3Bucket", "DynamoTable"):
                    self.assertIn(("kro.run", kind), kinds)
                self.assertIn(("apps", "StatefulSet"), kinds)
                for kind in (("", "Pod"), ("apps", "ReplicaSet"), ("apps", "ControllerRevision"), ("discovery.k8s.io", "EndpointSlice"), ("", "PersistentVolumeClaim")):
                    self.assertIn(kind, kinds)
                self.assertIn("https://opspresso.github.io/helm-charts", project["spec"]["sourceRepos"])
                self.assertNotIn(("", "Secret"), kinds)
                self.assertNotIn(("kro.run", "ResourceGraphDefinition"), kinds)
                self.assertEqual(project["spec"]["clusterResourceWhitelist"], [{"group": "", "kind": "Namespace"}])

    def test_this_chart_declares_no_runway_application(self):
        for context in self.contexts():
            values = rendered_values(context["cluster"])
            kinds = {r["kind"] for r in values["raw"]["resources"]}
            self.assertFalse(kinds & {"Application", "ApplicationSet"})
