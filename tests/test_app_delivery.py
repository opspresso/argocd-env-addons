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

    def test_the_profile_is_valid(self):
        for context in self.contexts():
            profile = context["app_delivery"]
            with self.subTest(cluster=context["cluster"]):
                environments = profile["environments"]
                self.assertTrue(environments)
                self.assertEqual(len(environments), len(set(environments)))
                for name in environments:
                    self.assertRegex(name, ENVIRONMENT_NAME)
                self.assertIn(profile["primary_environment"], environments)

    def test_one_application_per_allowed_environment_directory(self):
        for context in self.contexts():
            profile = context["app_delivery"]
            values = rendered_values(context["cluster"])
            appset = resource(values, "ApplicationSet", "projects")
            with self.subTest(cluster=context["cluster"]):
                directories = [d["path"] for g in appset["spec"]["generators"] for d in g["git"]["directories"]]
                self.assertEqual(directories, [f"projects/*/{name}" for name in profile["environments"]])
                spec = appset["spec"]["template"]["spec"]
                self.assertEqual(spec["destination"]["namespace"], "app-{{ index .path.segments 1 }}-{{ .path.basename }}")
                chart, resources = spec["sources"]
                parameters = {p["name"]: p["value"] for p in chart["helm"]["parameters"]}
                # The chart guard checks the environment against these parameters, which a values file cannot override.
                self.assertEqual(parameters["app.tenant.environments"], " ".join(profile["environments"]))
                self.assertEqual(parameters["app.tenant.primaryEnvironment"], profile["primary_environment"])
                self.assertEqual(parameters["app.tenant.tenantSecretsRoleArn"],
                                 f"arn:aws:iam::{context['aws_account_id']}:role/agent-runway-tenant-secrets")
                self.assertIn(f'eq .path.basename "{profile["primary_environment"]}"', parameters["app.routing.hosts[0]"])
                self.assertTrue(parameters["app.routing.hosts[0]"].endswith("." + profile["domain"]))
                self.assertEqual(chart["helm"]["valueFiles"], ["../../{{ .path.path }}/app.yaml"])
                self.assertTrue(chart["helm"]["ignoreMissingValueFiles"])
                self.assertEqual(resources["directory"], {"include": "resources.yaml"})

    def test_tenant_apps_may_create_only_the_app_kinds_and_platform_resources(self):
        for context in self.contexts():
            values = rendered_values(context["cluster"])
            project = resource(values, "AppProject", "projects")
            with self.subTest(cluster=context["cluster"]):
                kinds = {(k["group"], k["kind"]) for k in project["spec"]["namespaceResourceWhitelist"]}
                for kind in ("RdsPostgres", "S3Bucket", "DynamoTable"):
                    self.assertIn(("kro.run", kind), kinds)
                self.assertIn(("apps", "StatefulSet"), kinds)
                self.assertIn("https://opspresso.github.io/helm-charts", project["spec"]["sourceRepos"])
                self.assertNotIn(("", "Secret"), kinds)
                self.assertNotIn(("kro.run", "ResourceGraphDefinition"), kinds)
                self.assertEqual(project["spec"]["clusterResourceWhitelist"], [{"group": "", "kind": "Namespace"}])

    def test_each_chart_resource_is_an_application_at_its_pinned_version(self):
        for context in self.contexts():
            values = rendered_values(context["cluster"])
            appset = resource(values, "ApplicationSet", "project-resources")
            with self.subTest(cluster=context["cluster"]):
                paths = [item["path"] for item in appset["spec"]["generators"][0]["git"]["files"]]
                self.assertEqual(paths, [f"projects/*/{name}/resources/*.yaml" for name in context["app_delivery"]["environments"]])
                template = appset["spec"]["template"]
                self.assertEqual(template["metadata"]["finalizers"], ["resources-finalizer.argocd.argoproj.io"])
                chart, repository = template["spec"]["sources"]
                self.assertEqual((chart["chart"], chart["targetRevision"]), ("{{ .chart }}", "{{ .chartVersion }}"))
                self.assertEqual(chart["helm"]["releaseName"], "{{ .resourceName }}")
                self.assertEqual(repository["ref"], "values")
                self.assertEqual(template["spec"]["destination"]["namespace"], "app-{{ index .path.segments 1 }}-{{ index .path.segments 2 }}")


if __name__ == "__main__":
    unittest.main()
