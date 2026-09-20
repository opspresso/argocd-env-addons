#!/bin/bash

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)
DEMO_DIR="${ROOT_DIR}/../argocd-env-demo"

for command in kubectl helm aws python3; do
  command -v "$command" >/dev/null || { echo "Required command: $command" >&2; exit 1; }
done

run_kubectl() { kubectl --context orbstack "$@"; }
run_helm() { helm --kube-context orbstack "$@"; }

run_kubectl get node orbstack >/dev/null
test -f "${DEMO_DIR}/apps-orb.yaml"

umask 077
VALUES_FILE=$(mktemp)
trap 'rm -f "$VALUES_FILE"' EXIT

ARGOCD_PASSWORD=$(aws ssm get-parameter --name /k8s/common/argocd-password --with-decryption --query Parameter.Value --output text)
ARGOCD_MTIME=$(aws ssm get-parameter --name /k8s/common/argocd-mtime --with-decryption --query Parameter.Value --output text)

export ARGOCD_PASSWORD ARGOCD_MTIME

# Use the generated cluster values for bootstrap as well as the GitOps Application.
python3 - "${ROOT_DIR}/charts/argo-cd/orb/values-orb-demo.yaml" > "$VALUES_FILE" <<'PY'
import os
import sys
import yaml

with open(sys.argv[1]) as file:
    values = yaml.safe_load(file)["argo-cd"]
configs = values.setdefault("configs", {})
configs.setdefault("params", {})["server.insecure"] = True
configs["secret"] = {
    "argocdServerAdminPassword": os.environ["ARGOCD_PASSWORD"],
    "argocdServerAdminPasswordMtime": os.environ["ARGOCD_MTIME"],
}
yaml.safe_dump(values, sys.stdout)
PY

ARGOCD_VERSION=$(python3 - "${ROOT_DIR}/charts/argo-cd/Chart.yaml" <<'PY'
import sys
import yaml
with open(sys.argv[1]) as file:
    print(yaml.safe_load(file)["version"])
PY
)

run_helm repo add argo https://argoproj.github.io/argo-helm --force-update
run_helm repo update argo
run_helm upgrade --install argocd argo/argo-cd \
  --version "$ARGOCD_VERSION" --namespace argocd --create-namespace \
  --values "$VALUES_FILE" --wait --timeout 5m

run_kubectl apply -f "${ROOT_DIR}/install/k3s/projects.yaml"
run_kubectl apply -f "${ROOT_DIR}/addons-orb.yaml"
run_kubectl apply -f "${DEMO_DIR}/apps-orb.yaml"

echo "Argo CD: http://argocd-server.argocd.svc.cluster.local"
echo "GitOps status: kubectl --context orbstack -n argocd get applications"
