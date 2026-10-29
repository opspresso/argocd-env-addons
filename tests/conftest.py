"""Import the standalone automation modules from scripts/ and fetch chart dependencies."""

from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture(scope="session", autouse=True)
def chart_dependencies():
    """Fetch the upstream charts that tests render with helm template.

    scripts/validate.py fetches dependencies only for charts that an addon
    manifest deploys. Tests also render charts that no cluster deploys, so a
    clean checkout needs this step. Charts with all dependencies present are
    skipped.
    """
    for chart in sorted((ROOT / "charts").iterdir()):
        if not (chart / "Chart.yaml").is_file():
            continue

        listed = subprocess.run(
            ["helm", "dependency", "list", str(chart)],
            capture_output=True, text=True, check=True,
        )
        rows = listed.stdout.splitlines()[1:]

        if all(row.split()[-1] == "ok" for row in rows if row.strip()):
            continue

        subprocess.run(
            ["helm", "dependency", "update", str(chart)],
            capture_output=True, text=True, check=True,
        )
