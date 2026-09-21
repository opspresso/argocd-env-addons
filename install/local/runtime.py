"""Shared local Kubernetes context validation for installation and connections."""

import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from workload_policy import policy_errors


LOCAL_CONTEXTS = {"orbstack", "docker-desktop"}


def resolve_context(explicit=None):
    context = explicit or os.environ.get("KUBE_CONTEXT")
    if not context:
        context = subprocess.check_output(["kubectl", "config", "current-context"], text=True).strip()
    if context not in LOCAL_CONTEXTS:
        raise ValueError(f"Local deployment requires one of {sorted(LOCAL_CONTEXTS)}; got {context!r}")
    return context


def check_argocd_policy(context):
    manifest = subprocess.check_output(
        ["helm", "--kube-context", context, "get", "manifest", "argocd", "--namespace", "argocd"], text=True,
    )
    errors = policy_errors(manifest, "local")
    if errors:
        raise ValueError("Existing Argo CD violates local workload policy; reconcile its Helm resource settings:\n" + "\n".join(errors))


if __name__ == "__main__":
    try:
        context = resolve_context(sys.argv[1] if len(sys.argv) > 1 else None)
        if "--check-argocd" in sys.argv[2:]:
            check_argocd_policy(context)
        else:
            print(context)
    except (ValueError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
