"""Exercise the shell updater against isolated chart files."""

import json
import shutil
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/update_charts.sh"


def setup_repo(tmp_path, versions, charts):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "config").mkdir()
    script = tmp_path / "scripts/update_charts.sh"
    shutil.copy2(SCRIPT, script)
    (tmp_path / "config/versions.json").write_text(json.dumps({"versions": versions}))
    for name, content in charts.items():
        chart_dir = tmp_path / "charts" / name
        chart_dir.mkdir(parents=True)
        (chart_dir / "Chart.yaml").write_text(content)
    return script


def run(script, *args):
    return subprocess.run(
        ["bash", str(script), *args],
        cwd=script.parent.parent / "config",
        capture_output=True,
        text=True,
    )


def test_updates_wrapper_and_matching_dependencies_without_reformatting(tmp_path):
    istio = (
        'name: istio\nversion: "1.30.4" # upstream\n\n'
        'dependencies:\n- name: base\n  repository: https://example.com/istio\n  version: "1.30.4" # base\n\n'
        '- name: istiod\n  repository: https://example.com/istio\n  version: "1.30.4" # istiod\n\n'
        '- name: gateway\n  repository: https://example.com/istio\n  version: "1.30.4" # gateway\n\n'
        '- name: raw\n  repository: https://example.com/raw\n  version: "1.30.4" # unrelated\n'
    )
    other = 'name: other\nversion: "1.0.0"\n'
    script = setup_repo(
        tmp_path,
        {
            "istiod": {"path": "istio", "chart": "istio/istiod", "current": "1.30.4", "version": "1.30.5"},
            "other": {"chart": "test/other", "current": "1.0.0", "version": "2.0.0", "locked": True},
            "missing": {"chart": "test/missing", "version": "2.0.0"},
        },
        {"istio": istio, "other": other},
    )
    chart_file = tmp_path / "charts/istio/Chart.yaml"

    assert run(script, "--dry-run").returncode == 0
    assert chart_file.read_text() == istio

    result = run(script, "--chart", "istio")
    assert result.returncode == 0, result.stderr
    assert chart_file.read_text() == istio.replace("1.30.4", "1.30.5", 4)
    assert (tmp_path / "charts/other/Chart.yaml").read_text() == other
    assert json.loads((tmp_path / "config/versions.json").read_text())["versions"]["istiod"]["current"] == "1.30.4"
    assert run(script, "--chart", "istio").returncode == 0
    assert chart_file.read_text() == istio.replace("1.30.4", "1.30.5", 4)


def test_stale_current_aborts_before_any_write(tmp_path):
    chart = 'name: first\nversion: "1.0.0"\n'
    script = setup_repo(
        tmp_path,
        {
            "first": {"chart": "test/first", "current": "1.0.0", "version": "2.0.0"},
            "second": {"chart": "test/second", "current": "0.9.0", "version": "2.0.0"},
        },
        {"first": chart, "second": chart.replace("first", "second")},
    )
    result = run(script)
    assert result.returncode != 0
    assert "recorded current" in result.stderr
    assert (tmp_path / "charts/first/Chart.yaml").read_text() == chart


def test_dependency_mismatch_fails_without_overwriting_chart(tmp_path):
    chart = (
        'name: first\nversion: "1.0.0"\ndependencies:\n'
        '- name: first\n  repository: https://example.com/test\n  version: "0.9.0"\n'
    )
    script = setup_repo(
        tmp_path,
        {"first": {"chart": "test/first", "current": "1.0.0", "version": "2.0.0"}},
        {"first": chart},
    )
    result = run(script)
    assert result.returncode != 0
    assert "no dependency matches" in result.stderr
    assert (tmp_path / "charts/first/Chart.yaml").read_text() == chart
