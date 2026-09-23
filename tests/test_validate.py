import subprocess
import sys

import pytest
import yaml

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
      releaseName: external-secrets
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
    assert targets[0]["release_name"] == "external-secrets"


@pytest.mark.parametrize("release_name", [None, "cert-manager"])
def test_render_uses_the_configured_helm_release_name(tmp_path, monkeypatch, release_name):
    source = {"path": "charts/cert-manager"}
    if release_name is not None:
        source["helm"] = {"releaseName": release_name}
    (tmp_path / "app.yaml").write_text(yaml.safe_dump({
        "kind": "Application",
        "metadata": {"name": "cert-manager-k3s"},
        "spec": {"source": source, "destination": {"namespace": "cert-manager"}},
    }))
    calls = []

    def helm_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(validate.subprocess, "run", helm_run)
    target, = validate.load_targets([str(tmp_path)])

    assert validate.render(target, None) is None
    assert calls[0][:4] == ["helm", "template", release_name or "cert-manager-k3s",
                           "charts/cert-manager"]


@pytest.mark.parametrize("directory_exists", [False, True])
def test_validation_rejects_missing_or_empty_application_directory(
    tmp_path, monkeypatch, capsys, directory_exists
):
    addons = tmp_path / "addons"
    if directory_exists:
        addons.mkdir()
    monkeypatch.setattr(sys, "argv", ["validate.py", "-d", str(addons)])

    assert validate.main() == 1
    assert "FAIL" in capsys.readouterr().out


def test_load_targets_rejects_missing_additional_directory(tmp_path):
    addons = tmp_path / "addons"
    addons.mkdir()
    missing = tmp_path / "misspelled-addons"

    with pytest.raises(FileNotFoundError, match="Application directory does not exist"):
        validate.load_targets([str(addons), str(missing)])


@pytest.mark.parametrize("operation", ["dependencies", "render"])
def test_silent_failed_helm_command_remains_a_failure(monkeypatch, operation):
    monkeypatch.setattr(validate.subprocess, "run", lambda args, **kwargs:
                        subprocess.CompletedProcess(args, 1, stdout="", stderr=""))

    if operation == "dependencies":
        error = validate.update_dependencies("charts/example")
    else:
        error = validate.render({
            "name": "example", "chart": "charts/example", "namespace": "default",
            "value_files": [], "appset": "addons/eks/example.yaml",
        }, None)

    assert "exit code 1" in error


def test_failed_dependencies_skip_every_application_using_the_chart(
    tmp_path, monkeypatch, capsys
):
    addons = tmp_path / "addons" / "eks"
    addons.mkdir(parents=True)
    charts = tmp_path / "charts"
    charts.mkdir()
    failed_chart = str(charts / "failed")
    healthy_chart = str(charts / "healthy")

    for name, chart in [("failed-a", failed_chart), ("failed-b", failed_chart),
                        ("healthy", healthy_chart)]:
        (addons / (name + ".yaml")).write_text(yaml.safe_dump({
            "kind": "Application",
            "metadata": {"name": name},
            "spec": {"source": {"path": chart}, "destination": {"namespace": "default"}},
        }))

    calls = []

    def helm_run(args, **kwargs):
        calls.append(args)
        if args[1:3] == ["dependency", "update"] and args[3] == failed_chart:
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="upstream unavailable")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(sys, "argv", ["validate.py", "-d", str(addons)])
    monkeypatch.setattr(validate, "CHARTS_DIR", str(charts))
    monkeypatch.setattr(validate.subprocess, "run", helm_run)

    assert validate.main() == 1
    assert calls == [
        ["helm", "dependency", "update", failed_chart],
        ["helm", "dependency", "update", healthy_chart],
        ["helm", "template", "healthy", healthy_chart, "--namespace", "default"]
        + [arg for api in validate.API_VERSIONS for arg in ["--api-versions", api]],
    ]
    output = capsys.readouterr().out
    assert "1 renders, 1 failures" in output
    assert "upstream unavailable" in output


def test_application_set_without_environments_cannot_report_success(tmp_path, monkeypatch, capsys):
    addons = tmp_path / "addons"
    addons.mkdir()
    charts = tmp_path / "charts"
    charts.mkdir()
    (addons / "empty.yaml").write_text(yaml.safe_dump({
        "kind": "ApplicationSet",
        "spec": {
            "generators": [{"git": {"files": []}}],
            "template": {
                "metadata": {"name": "empty"},
                "spec": {"source": {"path": "charts/empty"},
                         "destination": {"namespace": "default"}},
            },
        },
    }))
    monkeypatch.setattr(sys, "argv", ["validate.py", "-d", str(addons)])
    monkeypatch.setattr(validate, "CHARTS_DIR", str(charts))
    monkeypatch.setattr(validate.subprocess, "run", lambda args, **kwargs:
                        subprocess.CompletedProcess(args, 0, stdout="", stderr=""))

    assert validate.main() == 1
    assert "no Application environments were rendered" in capsys.readouterr().out
