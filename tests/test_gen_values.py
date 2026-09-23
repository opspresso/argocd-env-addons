from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest
import yaml

import gen_values


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def chart(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "env").mkdir()
    chart = tmp_path / "charts/example"
    chart.mkdir(parents=True)
    (chart / "values-template.yaml.j2").write_text('targetGroupARN: "{{target_group.public_http}}"\n')
    return chart


def write_env(name, **extra):
    data = {"cluster": name, "env": "eks", "target_group": {"public_http": "arn:example"}, **extra}
    Path(f"env/{name}.yaml").write_text(yaml.safe_dump(data))


def render():
    gen_values.gen_repos(SimpleNamespace(reponame="example", platform="eks"), "yaml.j2")


def test_missing_required_value_fails_before_replacing_any_outputs(chart):
    write_env("a-valid")
    write_env("z-invalid", target_group={})
    output = chart / "eks/values-a-valid.yaml"
    output.parent.mkdir()
    output.write_text("previous output\n")

    with pytest.raises(ValueError, match=r"env/z-invalid.yaml.*values-template.yaml.j2.*public_http"):
        render()

    assert output.read_text() == "previous output\n"
    assert not (chart / "eks/values-z-invalid.yaml").exists()


@pytest.mark.parametrize("contents, message", [
    ("cluster: different\nenv: eks\n", "cluster.*match the filename"),
    ("cluster: example\nenv: eKs\n", "'env' must be"),
    ("- item\n", "YAML mapping"),
])
def test_invalid_environment_cannot_write_values(chart, contents, message):
    Path("env/example.yaml").write_text(contents)
    with pytest.raises(ValueError, match=message):
        render()
    assert not (chart / "eks").exists()


def test_explicit_optional_default_still_renders(chart):
    write_env("example")
    (chart / "values-template.yaml.j2").write_text('value: "{{optional | default(\'fallback\')}}"\n')
    render()
    assert yaml.safe_load((chart / "eks/values-example.yaml").read_text()) == {"value": "fallback"}


def test_missing_yaml_block_keeps_the_field_name_in_the_error(chart):
    write_env("example", target_group={})
    (chart / "values-template.yaml.j2").write_text("{{target_group.public_http | to_yaml}}\n")
    with pytest.raises(ValueError, match=r"env/example.yaml.*values-template.yaml.j2.*public_http"):
        render()


def test_cli_reports_context_and_nonzero_status_on_missing_value(chart):
    write_env("example", target_group={})
    Path("scripts").mkdir()
    shutil.copy2(ROOT / "scripts/gen_values.py", "scripts/gen_values.py")
    result = subprocess.run(
        [sys.executable, "scripts/gen_values.py", "-r", "example"], capture_output=True, text=True
    )
    assert result.returncode == 1
    assert "env/example.yaml" in result.stderr
    assert "charts/example/values-template.yaml.j2" in result.stderr
    assert "public_http" in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_rejects_an_unknown_chart(chart):
    Path("scripts").mkdir()
    shutil.copy2(ROOT / "scripts/gen_values.py", "scripts/gen_values.py")
    result = subprocess.run(
        [sys.executable, "scripts/gen_values.py", "-r", "missing"], capture_output=True, text=True
    )
    assert result.returncode == 1
    assert "charts/missing: values template not found" in result.stderr
    assert not Path("charts/missing").exists()
