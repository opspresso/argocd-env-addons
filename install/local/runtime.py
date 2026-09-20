"""Shared local Kubernetes context validation for installation and connections."""

import os
import subprocess
import sys


LOCAL_CONTEXTS = {"orbstack", "docker-desktop"}


def resolve_context(explicit=None):
    context = explicit or os.environ.get("KUBE_CONTEXT")
    if not context:
        context = subprocess.check_output(["kubectl", "config", "current-context"], text=True).strip()
    if context not in LOCAL_CONTEXTS:
        raise ValueError(f"Local deployment requires one of {sorted(LOCAL_CONTEXTS)}; got {context!r}")
    return context


if __name__ == "__main__":
    try:
        print(resolve_context(sys.argv[1] if len(sys.argv) > 1 else None))
    except (ValueError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
