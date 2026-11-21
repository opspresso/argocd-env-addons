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


def test_unavailable_page_loads_nothing_from_outside():
    # The gateway serves the page while services are down, so it must not
    # depend on fonts, scripts or images from another host.
    page = (ROOT / "charts/istio/unavailable-page.html").read_text()
    assert not re.search(r"(https?:)?//[a-z0-9.-]+\.[a-z]{2,}", page, re.IGNORECASE)


def test_rendered_envoy_filter_carries_the_page_verbatim():
    page = (ROOT / "charts/istio/unavailable-page.html").read_text()
    for path in sorted((ROOT / "charts/istio/eks").glob("values-*.yaml")):
        values = yaml.safe_load(path.read_text())
        envoy_filter = next(r for r in values["raw"]["resources"] if r["metadata"]["name"] == "unavailable-page")
        patch = envoy_filter["spec"]["configPatches"][0]["patch"]["value"]["typed_config"]
        mappers = patch["local_reply_config"]["mappers"]
        assert len(mappers) == 2, path
        for mapper in mappers:
            body = mapper["body_format_override"]["text_format_source"]["inline_string"]
            assert body.rstrip("\n") == page.rstrip("\n"), path
