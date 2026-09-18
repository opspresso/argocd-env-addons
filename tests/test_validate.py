import validate


def test_load_targets_includes_direct_applications(tmp_path):
    addons = tmp_path / "addons" / "k3s"
    addons.mkdir(parents=True)
    (addons / "external-secrets.yaml").write_text(
        """\
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: external-secrets-k3s
spec:
  source:
    path: charts/external-secrets
    helm:
      valueFiles:
        - values.yaml
  destination:
    namespace: addon-external-secrets
"""
    )

    targets = validate.load_targets([str(tmp_path / "addons")])

    assert len(targets) == 1
    assert targets[0]["chart"] == "charts/external-secrets"
    assert targets[0]["env_files"] == [None]
    assert targets[0]["value_files"] == ["values.yaml"]
