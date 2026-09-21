#!/usr/bin/env python3
"""Project existing local credentials into service namespaces without rotating them."""

import base64
import json
import subprocess
import sys

from runtime import resolve_context


TARGETS = (
    ("agent-studio", "postgresql-credentials", "local-credentials", {"postgres-password": "POSTGRES_PASSWORD", "password": "POSTGRES_PASSWORD"}),
    ("agent-studio", "minio-credentials", "local-credentials", {"root-user": "MINIO_ROOT_USER", "root-password": "MINIO_ROOT_PASSWORD"}),
    ("agent-memory", "memory-neo4j-auth", "local-credentials", {"NEO4J_AUTH": "NEO4J_AUTH"}),
    ("agent-mcps", "mcp-argocd-external", "local-mcp-argocd", {"ARGOCD_API_TOKEN": "ARGOCD_API_TOKEN"}),
)


def projected_secrets(sources):
    secrets = []
    for namespace, name, source, mapping in TARGETS:
        data = {}
        for target_key, source_key in mapping.items():
            value = sources[source].get("data", {}).get(source_key)
            if not value or not base64.b64decode(value) or b"REPLACE_" in base64.b64decode(value):
                raise ValueError(f"Set {source_key} in Secret local/{source}; credentials.example.yaml documents the required inputs")
            data[target_key] = value
        secrets.append({"apiVersion": "v1", "kind": "Secret", "metadata": {"name": name, "namespace": namespace}, "type": "Opaque", "data": data})
    return secrets


def main():
    context = resolve_context(sys.argv[1] if len(sys.argv) > 1 else None)
    kubectl = ["kubectl", "--context", context]

    def get(kind, name, namespace=None):
        args = kubectl + ["get", kind, name, "--ignore-not-found", "-o", "json"]
        if namespace:
            args += ["--namespace", namespace]
        result = subprocess.check_output(args, text=True)
        return json.loads(result) if result.strip() else None

    sources = {}
    for name in sorted({source for _, _, source, _ in TARGETS}):
        source = get("secret", name, "local")
        if source is None:
            raise ValueError(f"Missing Secret local/{name}; prepare the existing credentials before installing services")
        sources[name] = source
    pending = []
    for secret in projected_secrets(sources):
        metadata = secret["metadata"]
        current = get("secret", metadata["name"], metadata["namespace"])
        if current is not None:
            if current.get("data") != secret["data"]:
                raise ValueError(f"Secret {metadata['namespace']}/{metadata['name']} differs; coordinate credential rotation with the stored service data")
        else:
            pending.append(secret)
    for namespace in sorted({secret["metadata"]["namespace"] for secret in pending}):
        if get("namespace", namespace) is None:
            subprocess.run(kubectl + ["create", "namespace", namespace], check=True)
    for secret in pending:
        subprocess.run(kubectl + ["create", "-f", "-"], input=json.dumps(secret), text=True, check=True)
    print("Local service credentials are ready; existing values were preserved.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
