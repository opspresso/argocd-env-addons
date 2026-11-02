from pathlib import Path
import unittest

from jinja2 import Environment, FileSystemLoader
import yaml

from gen_values import to_yaml


ROOT = Path(__file__).resolve().parents[1]


def graph():
    environment = Environment(loader=FileSystemLoader(ROOT / "charts/kro"))
    environment.filters["to_yaml"] = to_yaml
    context = yaml.safe_load((ROOT / "env/eks-demo.yaml").read_text())
    values = yaml.safe_load(environment.get_template("values-template.yaml.j2").render(context))
    return next(r for r in values["raw"]["resources"] if r["kind"] == "ResourceGraphDefinition" and r["metadata"]["name"] == "dynamo-table")


class DynamoTableTemplateTests(unittest.TestCase):
    def test_tables_are_tagged_for_the_tenant_role_and_never_share_a_name(self):
        rgd = graph()
        self.assertEqual((rgd["spec"]["schema"]["apiVersion"], rgd["spec"]["schema"]["kind"]), ("v1alpha1", "DynamoTable"))
        table = next(r for r in rgd["spec"]["resources"] if r["id"] == "table")["template"]["spec"]
        # ACK adopts an existing table of the same name; 128 bits keep a tenant from finding another tenant's name.
        self.assertTrue(table["tableName"].startswith('${"app-" + "%x".format([hash.sha256("eks-demo/" + schema.metadata.namespace'))
        self.assertIn("substring(0, 32)", table["tableName"])
        self.assertEqual(table["billingMode"], "PAY_PER_REQUEST")
        self.assertEqual({t["key"]: t["value"] for t in table["tags"]}["kubernetes-namespace"], "${schema.metadata.namespace}")

    def test_the_pod_identity_agent_is_the_only_added_address(self):
        policy = next(r for r in graph()["spec"]["resources"] if r["id"] == "networkPolicy")["template"]
        self.assertEqual(policy["spec"]["egress"], [{"to": [{"ipBlock": {"cidr": "169.254.170.23/32"}}], "ports": [{"protocol": "TCP", "port": 80}]}])


if __name__ == "__main__":
    unittest.main()
