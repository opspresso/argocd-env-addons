#!/usr/bin/env python3
"""Render bootstrap values without interpreting secrets as YAML or sed syntax.

Cluster settings (hostname, admin groups) come from env/<CLUSTER>.yaml, the
same file the addons render from. Secrets come from SSM; secrets.sh and token.sh
create them before this runs. The bootstrap signs in with the admin account only.
"""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import yaml


SCRIPT_DIR = Path(__file__).resolve().parent
ENV_DIR = SCRIPT_DIR.parents[1] / "env"
NOT_FOUND = "(ParameterNotFound)"


def aws(*args):
    result = subprocess.run(
        ["aws", *args], capture_output=True, text=True, check=False
    )
    if result.returncode:
        if NOT_FOUND in result.stderr:
            raise ValueError(f"SSM 파라미터가 없습니다: {args[args.index('--name') + 1]}")
        # Do not include captured output, which may contain decrypted values.
        raise ValueError(f"AWS {args[0]} {args[1]} 조회 실패 (종료 코드 {result.returncode})")
    return result.stdout


def ssm(name):
    print(f"  ssm  {name}")
    try:
        response = json.loads(
            aws("ssm", "get-parameter", "--name", name, "--with-decryption", "--output", "json")
        )
        value = response["Parameter"]["Value"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise ValueError(f"SSM 응답이 올바르지 않습니다: {name}") from error
    if not isinstance(value, str) or not value:
        raise ValueError(f"SSM 값이 비어 있거나 문자열이 아닙니다: {name}")
    return value


def replace_values(value, replacements):
    if isinstance(value, dict):
        return {key: replace_values(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_values(item, replacements) for item in value]
    if isinstance(value, str):
        # Inserted secrets may contain placeholder names and must not be
        # interpreted a second time.
        return re.sub(
            "|".join(re.escape(key) for key in replacements),
            lambda match: replacements[match.group()],
            value,
        )
    return value


def cluster_settings(cluster):
    path = ENV_DIR / f"{cluster}.yaml"
    try:
        env = yaml.safe_load(path.read_text())
        hostname = env["argocd"]["hostname"]
        groups = env["sso"]["admin_groups"]
    except (OSError, KeyError, TypeError) as error:
        raise ValueError(f"{path.name}에 argocd.hostname, sso.admin_groups가 필요합니다") from error
    if not (isinstance(hostname, str) and hostname) or \
            not groups or not all(isinstance(group, str) and group for group in groups):
        raise ValueError(f"{path.name}의 argocd.hostname, sso.admin_groups가 비어 있습니다")
    return hostname, groups


def build():
    cluster = os.environ.get("CLUSTER", "eks-demo")
    hostname, groups = cluster_settings(cluster)
    replacements = {
        "ARGOCD_HOSTNAME": hostname,
        "ADMIN_GROUPS_POLICY": "\n".join(f"g, {group}, role:admin" for group in groups),
    }
    replacements.update({
        key: ssm(f"/k8s/common/{name}")
        for key, name in (
            ("ARGOCD_PASSWORD", "argocd-password"),
            ("ARGOCD_MTIME", "argocd-mtime"),
            ("ARGOCD_SERVER_SECRET", "argocd-server-secret"),
            ("ARGOCD_WEBHOOK", "argocd-webhook"),
            ("ARGOCD_MCP_TOKENS", "argocd-mcp-tokens"),
        )
    })

    template = yaml.safe_load((SCRIPT_DIR / "values.yaml").read_text())
    values = replace_values(template, replacements)
    output = SCRIPT_DIR / "values.output.yaml"
    descriptor, temporary = tempfile.mkstemp(prefix=".values.output-", suffix=".tmp", dir=SCRIPT_DIR)
    try:
        # mkstemp creates a private (0600) file; replacement also repairs an
        # existing output file that was created with broader permissions.
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            yaml.safe_dump(values, stream, allow_unicode=True, sort_keys=False)
        os.replace(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)
    print("values.output.yaml 파일이 생성되었습니다.")


def main():
    try:
        build()
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
