from pathlib import Path
import unittest

from jinja2 import Environment, FileSystemLoader
import yaml

from gen_values import to_yaml


ROOT = Path(__file__).resolve().parents[1]


def render(**rds):
    environment = Environment(loader=FileSystemLoader(ROOT / "charts/kro"))
    environment.filters["to_yaml"] = to_yaml
    context = yaml.safe_load((ROOT / "env/eks-demo.yaml").read_text())
    context["delivery_resources"]["rds"].update(rds)
    return yaml.safe_load(environment.get_template("values-template.yaml.j2").render(context)) or {}


class RdsPostgresTemplateTests(unittest.TestCase):
    def test_the_template_waits_for_the_security_group(self):
        resources = render(security_group_id="").get("raw", {}).get("resources") or []
        self.assertNotIn("rds-postgres", [r["metadata"]["name"] for r in resources])

    def test_instances_are_private_and_reachable_only_from_their_namespace(self):
        values = render(security_group_id="sg-0123456789abcdef0")
        rgd = next(r for r in values["raw"]["resources"] if r["kind"] == "ResourceGraphDefinition")
        self.assertEqual((rgd["spec"]["schema"]["apiVersion"], rgd["spec"]["schema"]["kind"]), ("v1alpha1", "RdsPostgres"))
        resources = {r["id"]: r["template"] for r in rgd["spec"]["resources"]}
        db = resources["dbInstance"]["spec"]
        self.assertFalse(db["publiclyAccessible"])
        self.assertFalse(db["deletionProtection"])
        self.assertTrue(db["storageEncrypted"])
        self.assertEqual(db["vpcSecurityGroupIDs"], ["sg-0123456789abcdef0"])
        self.assertEqual(db["dbSubnetGroupName"], "app-delivery-rds")
        # TLS only: the parameter group sets rds.force_ssl=1 (terraform-env-demo demo/8-app-delivery).
        self.assertEqual(db["dbParameterGroupName"], "app-delivery-postgres18")
        # ACK skips the final snapshot by default; deletion must keep one with a name unique to the instance.
        annotations = resources["dbInstance"]["metadata"]["annotations"]
        self.assertEqual(annotations["rds.services.k8s.aws/skip-final-snapshot"], "false")
        self.assertIn("schema.metadata.uid", annotations["rds.services.k8s.aws/final-db-snapshot-identifier"])
        self.assertNotIn("rds.services.k8s.aws/delete-automated-backups", annotations)
        # The IAM policy of the ACK controller allows only db:app-* identifiers.
        self.assertTrue(db["dbInstanceIdentifier"].startswith('${"app-" +'))
        # The password comes from a Secret of the instance namespace, never from the manifest.
        self.assertEqual(db["masterUserPassword"]["namespace"], "${schema.metadata.namespace}")
        policy = resources["networkPolicy"]["spec"]
        self.assertEqual(policy["policyTypes"], ["Egress"])
        (rule,) = policy["egress"]
        self.assertEqual(rule["ports"], [{"protocol": "TCP", "port": 5432}])
        cidrs = [peer["ipBlock"]["cidr"] for peer in rule["to"]]
        context = yaml.safe_load((ROOT / "env/eks-demo.yaml").read_text())
        self.assertEqual(cidrs, context["delivery_resources"]["rds"]["subnet_cidrs"])
        # The DB subnets must not overlap the node and Pod subnets, or the policy would open other PostgreSQL servers.
        self.assertFalse(set(cidrs) & set(context["alloy_network_policy"]["node_cidrs"]))


if __name__ == "__main__":
    unittest.main()
