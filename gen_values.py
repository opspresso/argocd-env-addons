#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
import yaml

from jinja2 import Environment, FileSystemLoader


REPONAME = "sample-addon"


def parse_args():
    p = argparse.ArgumentParser(description="Helm chart gen")
    p.add_argument("-r", "--reponame", default=REPONAME, help="reponame")
    return p.parse_args()


def gen_repos(args, ext="yaml"):
    template_name = "values-template.{}".format(ext)
    template_path = "charts/{}/{}".format(args.reponame, template_name)

    if os.path.exists(template_path):
        print("# gen_values", template_path)

        e = Environment(loader=FileSystemLoader("charts/{}/".format(args.reponame)))
        t = e.get_template(template_name)

        gen_values(t, args.reponame)


def gen_values(t, reponame):
    for env_file in os.listdir("env"):
        if env_file.endswith(".yaml"):
            # print("")

            env_path = "env/{}".format(env_file)
            # print("# env ", env_path)

            save_root = "charts/{}/demo".format(reponame)
            save_path = "{}/values-{}".format(save_root, env_file)

            with open(env_path, "r") as vars:
                v = yaml.safe_load(vars)
                d = t.render(v)

                if d != None:
                    os.makedirs(save_root, exist_ok=True)

                    with open(save_path, "w") as file:
                        print("# save", save_path)
                        file.write(d)


def main():
    args = parse_args()

    os.makedirs("build", exist_ok=True)
    os.makedirs("charts", exist_ok=True)

    gen_repos(args, "yaml")
    gen_repos(args, "yaml.j2")


if __name__ == "__main__":
    main()
