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

    def test_the_tree_shows_every_namespaced_kind_and_only_namespaces_at_cluster_scope(self):
        for context in self.contexts():
            values = rendered_values(context["cluster"])
            project = resource(values, "AppProject", "projects")
            with self.subTest(cluster=context["cluster"]):
                self.assertEqual(project["spec"]["namespaceResourceWhitelist"], [{"group": "*", "kind": "*"}])
                self.assertIn("https://opspresso.github.io/helm-charts", project["spec"]["sourceRepos"])
                self.assertEqual(project["spec"]["clusterResourceWhitelist"], [{"group": "", "kind": "Namespace"}])

    def test_this_chart_declares_no_runway_application(self):
        for context in self.contexts():
            values = rendered_values(context["cluster"])
            kinds = {r["kind"] for r in values["raw"]["resources"]}
            self.assertFalse(kinds & {"Application", "ApplicationSet"})
