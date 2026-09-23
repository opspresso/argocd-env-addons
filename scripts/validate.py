#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render every Application or ApplicationSet the way Argo CD would, and fail on any error.

Reads addons/**/*.yaml, expands the git files generator against the env files it
names, and runs `helm template` with the exact valueFiles Argo CD passes. A
broken template or a missing values file then fails CI instead of surfacing as
a failed sync on the cluster.

Also enforces that every <env>/values-<cluster>.yaml has a values-template.yaml.j2
to come from - a hand-written one is indistinguishable from a render and drifts
without anyone noticing.

    ./scripts/validate.py                 # every Application or ApplicationSet in addons/{eks,k3s}/
    ./scripts/validate.py -r grafana      # one chart
    ./scripts/validate.py -d addons -d backup

backup/ is not checked by default: those addons are not deployed, and an
upstream chart that has gone away there should not block unrelated changes.
"""

import argparse
import os
import re
import subprocess
import sys

import yaml

from workload_policy import policy_errors, target_platform


APPSET_DIR = "addons"
CHARTS_DIR = "charts"

TEMPLATE = "values-template.yaml.j2"
VALUES_RE = re.compile(r"^values-.+\.yaml$")

# ApplicationSet substitutes {{key}} from the env file the generator matched.
PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")

# Argo CD renders against the destination cluster, so a chart guarded by
# .Capabilities.APIVersions.Has sees the CRDs installed there. `helm template`
# assumes none exist and silently drops those resources instead of failing,
# which reads as a clean run right up until the sync produces something CI never
# looked at - argo-cd renders four ServiceMonitors on the cluster and none here.
#
# Only the prometheus-operator CRDs need declaring: charts gate on those, while
# the gateway-api and external-secrets resources come from the raw chart
# unconditionally. Has() matches the exact string, so a chart asking for
# group/version/Kind is not satisfied by group/version.
API_VERSIONS = [
    "monitoring.coreos.com/v1",
    "monitoring.coreos.com/v1/PrometheusRule",
    "monitoring.coreos.com/v1/ServiceMonitor",
]


def parse_args():
    p = argparse.ArgumentParser(description="Helm render check")
    p.add_argument("-r", "--reponame", help="only this chart")
    p.add_argument(
        "-d", "--dir", action="append", dest="dirs",
        help="ApplicationSet directory (repeatable, default: {})".format(APPSET_DIR),
    )
    return p.parse_args()


def expand(text, env):
    def replace(match):
        key = match.group(1)
        if key not in env:
            raise KeyError("{{%s}} is not in the env file" % key)
        return str(env[key])

    return PLACEHOLDER.sub(replace, text)


def load_targets(dirs):
    """One entry per Application or ApplicationSet: chart and value files."""
    targets = []

    for directory in dirs:
        for current, _, names in os.walk(directory):
            for name in sorted(names):
                if not name.endswith(".yaml"):
                    continue

                path = os.path.join(current, name)
                with open(path, "r") as file:
                    doc = yaml.safe_load(file)

                if not doc or doc.get("kind") not in {"Application", "ApplicationSet"}:
                    continue

                if doc["kind"] == "ApplicationSet":
                    template = doc["spec"]["template"]
                    source = template["spec"]["source"]
                    env_files = [
                        entry["path"]
                        for generator in doc["spec"]["generators"]
                        for entry in generator["git"]["files"]
                    ]
                    name = template["metadata"]["name"]
                    namespace = template["spec"]["destination"]["namespace"]
                else:
                    source = doc["spec"]["source"]
                    env_files = [None]
                    name = doc["metadata"]["name"]
                    namespace = doc["spec"]["destination"]["namespace"]

                targets.append({
                    "appset": path,
                    "chart": source["path"],
                    "value_files": source.get("helm", {}).get("valueFiles", []),
                    "env_files": env_files,
                    "name": name,
                    "namespace": namespace,
                })

    return targets


def check_templates(only=None):
    """Every <env>/values-<cluster>.yaml has to be a render, never hand-written.

    A hand-maintained one looks exactly like a generated one, so it survives
    every build while quietly drifting from the template beside it.
    """
    failures = []

    for name in sorted(os.listdir(CHARTS_DIR)):
        chart_root = os.path.join(CHARTS_DIR, name)
        if not os.path.isdir(chart_root):
            continue

        if only and name != only:
            continue

        for platform in ("eks", "k3s", "local"):
            chart = os.path.join(chart_root, platform)
            if not os.path.isdir(chart):
                continue

            if os.path.exists(os.path.join(chart_root, TEMPLATE)):
                continue

            found = sorted(f for f in os.listdir(chart) if VALUES_RE.match(f))

            if found:
                failures.append((
                    chart,
                    "{} has no {}, so {} cannot be regenerated".format(
                        chart_root, TEMPLATE, ", ".join(found)
                    ),
                ))

    return failures


def update_dependencies(chart):
    """Fetch the upstream charts pinned in Chart.yaml."""
    print("# deps", chart, flush=True)

    result = subprocess.run(
        ["helm", "dependency", "update", chart], capture_output=True, text=True
    )

    if result.returncode != 0:
        return result.stderr.strip() or result.stdout.strip()

    return None


def render(target, env_file):
    """helm template one Application or ApplicationSet target."""
    env = {}
    if env_file:
        with open(env_file, "r") as file:
            env = yaml.safe_load(file)

    args = ["helm", "template", expand(target["name"], env), target["chart"]]
    args += ["--namespace", expand(target["namespace"], env)]

    for api_version in API_VERSIONS:
        args += ["--api-versions", api_version]

    for value_file in target["value_files"]:
        path = os.path.join(target["chart"], expand(value_file, env))

        # Argo CD fails the sync when a listed valueFile is missing, so a
        # chart that was never rendered has to fail here too.
        if not os.path.exists(path):
            return "missing values file: {}".format(path)

        args += ["-f", path]

    result = subprocess.run(args, capture_output=True, text=True)

    if result.returncode != 0:
        return result.stderr.strip() or result.stdout.strip()

    errors = policy_errors(result.stdout, target_platform(target, env))
    return "\n".join(errors) if errors else None


def main():
    args = parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(root)

    targets = load_targets(args.dirs or [APPSET_DIR])

    if args.reponame:
        wanted = "charts/{}".format(args.reponame)
        targets = [t for t in targets if t["chart"] == wanted]

        if not targets:
            print("no ApplicationSet uses {}".format(args.reponame))
            return 1

    failures = check_templates(args.reponame)
    rendered = 0
    prepared = set()

    for target in targets:
        if target["chart"] not in prepared:
            error = update_dependencies(target["chart"])
            prepared.add(target["chart"])

            if error:
                failures.append((target["chart"], error))
                continue

        for env_file in target["env_files"]:
            print("# render {} {}".format(target["appset"], env_file or "direct"), flush=True)

            try:
                error = render(target, env_file)
            except (KeyError, IOError) as exception:
                error = str(exception)

            rendered += 1

            if error:
                failures.append(
                    ("{} {}".format(target["appset"], env_file), error)
                )

    print("\n{} renders, {} failures".format(rendered, len(failures)))

    for where, why in failures:
        print("\nFAIL {}\n{}".format(where, why))

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
