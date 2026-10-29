from pathlib import Path
import unittest

from jinja2 import Environment, FileSystemLoader
import yaml

from gen_values import to_yaml


ROOT = Path(__file__).resolve().parents[1]


def context():
    return yaml.safe_load((ROOT / "env/eks-demo.yaml").read_text())


def render(**valkey):
    environment = Environment(loader=FileSystemLoader(ROOT / "charts/kro"))
    environment.filters["to_yaml"] = to_yaml
    values = context()
    values["delivery_resources"]["valkey"].update(valkey)
    return yaml.safe_load(environment.get_template("values-template.yaml.j2").render(values)) or {}


def graph(values):
    return next(r for r in values["raw"]["resources"] if r["kind"] == "ResourceGraphDefinition" and r["metadata"]["name"] == "valkey-cache")


class ValkeyCacheTemplateTests(unittest.TestCase):
    def test_the_template_waits_for_the_security_group(self):
        resources = render(security_group_id="").get("raw", {}).get("resources") or []
        self.assertNotIn("valkey-cache", [r["metadata"]["name"] for r in resources])

    def test_caches_are_private_and_need_their_own_user(self):
        rgd = graph(render(security_group_id="sg-0123456789abcdef0"))
        self.assertEqual((rgd["spec"]["schema"]["apiVersion"], rgd["spec"]["schema"]["kind"]), ("v1alpha1", "ValkeyCache"))
        resources = {r["id"]: r["template"] for r in rgd["spec"]["resources"]}
        cache = resources["serverlessCache"]["spec"]
        self.assertEqual(cache["engine"], "valkey")
        self.assertEqual(cache["securityGroupIDs"], ["sg-0123456789abcdef0"])
        valkey = context()["delivery_resources"]["valkey"]
        self.assertEqual(cache["subnetIDs"], valkey["subnet_ids"])
        # The cache admits only the members of its own user group; the group holds only the instance's user.
        self.assertEqual(cache["userGroupID"], "${userGroup.spec.userGroupID}")
        self.assertEqual(resources["userGroup"]["spec"]["userIDs"], ["${user.spec.userID}"])
        user = resources["user"]["spec"]
        self.assertEqual(user["authenticationMode"]["type"], "password")
        # The password comes from a Secret of the instance namespace, never from the manifest.
        (password,) = user["authenticationMode"]["passwords"]
        self.assertEqual(password["namespace"], "${schema.metadata.namespace}")
        # The IAM policy of the ACK controller allows only app-* identifiers.
        for kind, field in (("user", "userID"), ("userGroup", "userGroupID"), ("serverlessCache", "serverlessCacheName")):
            self.assertTrue(resources[kind]["spec"][field].startswith('${"app-" + "%x".format([hash.sha256('), kind)
            self.assertTrue(resources[kind]["spec"][field].endswith(".substring(0, 32)}"), kind)

    def test_only_the_instance_namespace_reaches_the_cache_subnets(self):
        rgd = graph(render(security_group_id="sg-0123456789abcdef0"))
        policy = next(r["template"]["spec"] for r in rgd["spec"]["resources"] if r["id"] == "networkPolicy")
        self.assertEqual(policy["policyTypes"], ["Egress"])
        (rule,) = policy["egress"]
        self.assertEqual(rule["ports"], [{"protocol": "TCP", "port": 6379}])
        values = context()
        cidrs = [peer["ipBlock"]["cidr"] for peer in rule["to"]]
        self.assertEqual(cidrs, values["delivery_resources"]["valkey"]["subnet_cidrs"])
        self.assertFalse(set(cidrs) & set(values["alloy_network_policy"]["node_cidrs"]))

    def test_usage_limits_match_the_catalog(self):
        spec = graph(render(security_group_id="sg-0123456789abcdef0"))["spec"]["schema"]["spec"]
        self.assertIn("minimum=1 maximum=10", spec["maxDataStorageGiB"])
        self.assertIn("minimum=1000 maximum=15000", spec["maxECPUPerSecond"])


if __name__ == "__main__":
    unittest.main()
