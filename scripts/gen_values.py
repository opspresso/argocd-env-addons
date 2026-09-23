#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
import sys
import yaml

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateError


REPONAME = "sample-addon"
PLATFORM = "eks"


def parse_args():
    p = argparse.ArgumentParser(description="Helm chart gen")
    p.add_argument("-r", "--reponame", default=REPONAME, help="reponame")
    p.add_argument("-p", "--platform", choices=["eks", "k3s", "local"], default=PLATFORM)
    return p.parse_args()


def to_yaml(value):
    """Render an env block as YAML so a template can pass it through whole
    with `{{ block | to_yaml | indent(2, first=true) }}` instead of mapping
    every key by hand."""
    if isinstance(value, StrictUndefined):
        # Let Jinja identify the missing field before PyYAML rejects the object.
        value = str(value)
    return yaml.safe_dump(value, default_flow_style=False, allow_unicode=True).rstrip("\n")


def gen_repos(args, ext="yaml"):
    template_name = "values-template.{}".format(ext)
    chart_path = "charts/{}".format(args.reponame)
    template_path = "{}/{}".format(chart_path, template_name)

    if os.path.exists(template_path):
        print("# gen_values", template_path)

        e = Environment(
            loader=FileSystemLoader("{}/".format(chart_path)),
            undefined=StrictUndefined,
        )
        e.filters["to_yaml"] = to_yaml
        try:
            t = e.get_template(template_name)
        except TemplateError as error:
            raise ValueError("{}: {}".format(template_path, error)) from error

        gen_values(t, args.reponame, args.platform)
        return True
    return False


def gen_values(t, reponame, platform):
    outputs = []
    for env_file in sorted(os.listdir("env")):
        if env_file.endswith(".yaml"):
            env_path = "env/{}".format(env_file)
            try:
                with open(env_path, "r") as variables:
                    v = yaml.safe_load(variables)
            except yaml.YAMLError as error:
                raise ValueError("{}: invalid YAML: {}".format(env_path, error)) from error

            if not isinstance(v, dict):
                raise ValueError("{} must contain a YAML mapping".format(env_path))
            if v.get("env") not in ("eks", "k3s", "local"):
                raise ValueError("{}: 'env' must be eks, k3s, or local".format(env_path))
            if v.get("cluster") != env_file[:-5]:
                raise ValueError("{}: 'cluster' must match the filename ({})".format(env_path, env_file[:-5]))

            if v["env"] != platform:
                continue

            try:
                rendered = t.render(v)
            except (TemplateError, yaml.YAMLError) as error:
                raise ValueError("{} with charts/{}/{}: {}".format(env_path, reponame, t.name, error)) from error
            outputs.append((env_file, rendered))

    # Validate every environment before replacing any existing output for this template.
    save_root = "charts/{}/{}".format(reponame, platform)
    for env_file, rendered in outputs:
        save_path = "{}/values-{}".format(save_root, env_file)
        os.makedirs(save_root, exist_ok=True)
        with open(save_path, "w") as file:
            print("# save", save_path)
            file.write(rendered)


def main():
    args = parse_args()

    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    os.makedirs("build", exist_ok=True)
    os.makedirs("charts", exist_ok=True)

    try:
        found_yaml = gen_repos(args, "yaml")
        found_jinja = gen_repos(args, "yaml.j2")
        if not (found_yaml or found_jinja):
            raise ValueError("charts/{}: values template not found".format(args.reponame))
    except (OSError, ValueError) as error:
        print("ERROR: {}".format(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
