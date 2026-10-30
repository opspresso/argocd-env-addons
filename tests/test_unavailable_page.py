from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[1]

# Envoy substitution commands the page may use. Any other percent sign would be
# parsed as a format command and break or garble the local reply.
ENVOY_COMMAND = re.compile(r"%(RESPONSE_CODE|RESPONSE_CODE_DETAILS|REQ\(X-REQUEST-ID\)(:\d+)?)%")


def test_unavailable_page_has_only_envoy_commands():
    page = (ROOT / "charts/istio/unavailable-page.html").read_text()
    assert "%" not in ENVOY_COMMAND.sub("", page)


def test_rendered_envoy_filter_carries_the_page_verbatim():
    page = (ROOT / "charts/istio/unavailable-page.html").read_text()
    for path in sorted((ROOT / "charts/istio/eks").glob("values-*.yaml")):
        values = yaml.safe_load(path.read_text())
        envoy_filter = next(r for r in values["raw"]["resources"] if r["metadata"]["name"] == "unavailable-page")
        patch = envoy_filter["spec"]["configPatches"][0]["patch"]["value"]["typed_config"]
        body = patch["local_reply_config"]["mappers"][0]["body_format_override"]["text_format_source"]["inline_string"]
        assert body.rstrip("\n") == page.rstrip("\n"), path
