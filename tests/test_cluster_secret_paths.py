from pathlib import Path
import unittest

from jinja2 import Environment, FileSystemLoader
import yaml

from gen_values import to_yaml


ROOT = Path(__file__).resolve().parents[1]


class ClusterSecretPathTests(unittest.TestCase):
    def test_alloy_uses_the_selected_clusters_memory_credential(self):
        context = yaml.safe_load((ROOT / "env/k3s-demo.yaml").read_text())
        context["cluster"] = "k3s-other"
        environment = Environment(loader=FileSystemLoader(ROOT / "charts/alloy"))
        environment.filters["to_yaml"] = to_yaml
        rendered = environment.get_template("values-template.yaml.j2").render(context)
        self.assertNotIn("/k8s/k3s-demo/", rendered)
        self.assertIn("/k8s/k3s-other/agent-memory/metrics-bearer-token", rendered)

    def test_common_values_do_not_choose_a_cluster_secret_namespace(self):
        clusters = [yaml.safe_load(path.read_text())["cluster"] for path in (ROOT / "env").glob("*.yaml")]
        for path in (ROOT / "charts").glob("*/values.yaml"):
            with self.subTest(chart=path.parent.name):
                parsed = yaml.safe_dump(yaml.safe_load(path.read_text()))
                self.assertFalse(any(f"/k8s/{cluster}" in parsed for cluster in clusters), str(path))


if __name__ == "__main__":
    unittest.main()
