import json
from types import SimpleNamespace

import pytest

import update_versions


@pytest.fixture
def repository(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(update_versions, "__file__", str(tmp_path / "scripts/update_versions.py"))
    (tmp_path / "config").mkdir()
    config = {"versions": {name: {"chart": f"test/{name}", "version": "1.0.0"} for name in ("first", "second")}}
    (tmp_path / "config/versions.json").write_text(json.dumps(config))
    (tmp_path / "README.md").write_text("# Charts\n<!--- BEGIN_VERSION --->\nold table\n<!--- END_VERSION --->\n")
    monkeypatch.setattr(update_versions, "get_latest_version", lambda *args: ("2.0.0", "v2"))
    return tmp_path


def run(monkeypatch, *, chart=None, dry_run=False):
    monkeypatch.setattr(update_versions, "parse_args", lambda: SimpleNamespace(chart=chart, dry_run=dry_run, verbose=False))
    return update_versions.main()


def test_readme_update_failure_is_a_failed_run(repository, monkeypatch):
    readme = repository / "README.md"
    readme.write_text("# Missing version markers\n")
    assert run(monkeypatch) == 1
    assert readme.read_text() == "# Missing version markers\n"
    assert json.loads((repository / "config/versions.json").read_text())["versions"]["first"]["version"] == "2.0.0"


def test_dry_run_preserves_both_outputs(repository, monkeypatch):
    paths = [repository / "README.md", repository / "config/versions.json"]
    before = [path.read_bytes() for path in paths]
    assert run(monkeypatch, dry_run=True) == 0
    assert [path.read_bytes() for path in paths] == before


def test_single_chart_updates_only_its_cache_and_preserves_full_table(repository, monkeypatch):
    before = (repository / "README.md").read_bytes()
    assert run(monkeypatch, chart="first") == 0
    config = json.loads((repository / "config/versions.json").read_text())["versions"]
    assert config["first"]["version"] == "2.0.0"
    assert config["second"]["version"] == "1.0.0"
    assert (repository / "README.md").read_bytes() == before
