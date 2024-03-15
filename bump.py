#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json


def get_charts(chart):
    txt = os.popen("helm search repo '{}' -o json".format(chart)).read()

    return json.loads(txt)


def main():
    filepath = "../helm-charts/versions.json"

    if os.path.exists(filepath):
        doc = None

        with open(filepath, "r") as file:
            doc = json.load(file)

            for k in doc["versions"]:
                chart = doc["versions"][k]["chart"]
                version = doc["versions"][k]["version"]

        if doc != None:
            with open(filepath, "w") as file:
                json.dump(doc, file, sort_keys=True, indent=2)


if __name__ == "__main__":
    main()
