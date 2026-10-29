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
    return next(r for r in values["raw"]["resources"] if r["kind"] == "ResourceGraphDefinition" and r["metadata"]["name"] == "s3-bucket")


class S3BucketTemplateTests(unittest.TestCase):
    def test_buckets_are_private_and_tagged_for_the_tenant_role(self):
        rgd = graph()
        self.assertEqual((rgd["spec"]["schema"]["apiVersion"], rgd["spec"]["schema"]["kind"]), ("v1alpha1", "S3Bucket"))
        (bucket,) = rgd["spec"]["resources"]
        spec = bucket["template"]["spec"]
        # The name never contains the namespace: ACK adopts an existing bucket of the same name, so names of two
        # namespaces must not be able to collide. The IAM scopes of ACK (eks-demo-*) and the tenant role rely on the prefix.
        self.assertTrue(spec["name"].startswith('${"eks-demo-" + "%x".format([hash.fnv64a("eks-demo/" + schema.metadata.namespace'))
        self.assertEqual(spec["publicAccessBlock"], dict.fromkeys(["blockPublicACLs", "ignorePublicACLs", "blockPublicPolicy", "restrictPublicBuckets"], True))
        self.assertEqual(spec["ownershipControls"], {"rules": [{"objectOwnership": "BucketOwnerEnforced"}]})
        self.assertEqual(spec["encryption"]["rules"][0]["applyServerSideEncryptionByDefault"], {"sseAlgorithm": "AES256"})
        # The tenant role (terraform-env-demo demo/8-agent-delivery) matches these tags; S3 reads them only with ABAC on.
        self.assertEqual(spec["abac"], {"status": "Enabled"})
        tags = {t["key"]: t["value"] for t in spec["tagging"]["tagSet"]}
        self.assertEqual(tags["eks-cluster-name"], "eks-demo")
        self.assertEqual(tags["kubernetes-namespace"], "${schema.metadata.namespace}")
        self.assertNotIn("policy", spec)


if __name__ == "__main__":
    unittest.main()
