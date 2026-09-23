#!/usr/bin/env python3
"""Render bootstrap values without interpreting secrets as YAML or sed syntax."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import yaml


SCRIPT_DIR = Path(__file__).resolve().parent


def aws(*args):
    result = subprocess.run(
        ["aws", *args], capture_output=True, text=True, check=False
    )
    if result.returncode:
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


def certificate_for(hostname):
    try:
        response = json.loads(
            aws("acm", "list-certificates", "--certificate-statuses", "ISSUED", "--output", "json")
        )
        certificates = response["CertificateSummaryList"]
        if not isinstance(certificates, list) or not all(isinstance(item, dict) for item in certificates):
            raise ValueError("ACM 인증서 목록이 올바르지 않습니다.")
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise ValueError("ACM 응답이 올바르지 않습니다.") from error
    for certificate in certificates:
        if certificate.get("DomainName") == hostname:
            arn = certificate.get("CertificateArn")
            if isinstance(arn, str) and arn.startswith("arn:"):
                return arn
            raise ValueError("ACM 인증서 ARN이 올바르지 않습니다.")
    raise ValueError("Argo CD 호스트와 DomainName이 일치하는 ISSUED ACM 인증서를 찾을 수 없습니다.")


def build():
    replacements = {
        key: ssm(f"/k8s/common/{name}")
        for key, name in (
            ("ARGOCD_HOSTNAME", "argocd-hostname"),
            ("GITHUB_ORG", "github-org"),
            ("GITHUB_TEAM", "github-team"),
            ("ARGOCD_PASSWORD", "argocd-password"),
            ("ARGOCD_MTIME", "argocd-mtime"),
            ("ARGOCD_SERVER_SECRET", "argocd-server-secret"),
            ("ARGOCD_WEBHOOK", "argocd-webhook"),
            ("ARGOCD_MCP_TOKENS", "argocd-mcp-tokens"),
        )
    }
    for key, name in (
        ("ARGOCD_GITHUB_ID", "argocd-github-id"),
        ("ARGOCD_GITHUB_SECRET", "argocd-github-secret"),
    ):
        replacements[key] = ssm(f"/k8s/{replacements['GITHUB_ORG']}/{name}")

    replacements["AWS_ACM_CERT"] = certificate_for(replacements["ARGOCD_HOSTNAME"])

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
