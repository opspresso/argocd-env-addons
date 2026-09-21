#!/bin/bash

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)
DEMO_DIR="${ROOT_DIR}/../argocd-env-demo"

for command in kubectl helm aws python3; do
  command -v "$command" >/dev/null || { echo "Required command: $command" >&2; exit 1; }
done

KUBE_CONTEXT=$(python3 "${SCRIPT_DIR}/runtime.py" "${KUBE_CONTEXT:-}")

run_kubectl() { kubectl --context "$KUBE_CONTEXT" "$@"; }
run_helm() { helm --kube-context "$KUBE_CONTEXT" "$@"; }

run_kubectl get nodes >/dev/null
test -f "${DEMO_DIR}/apps-local.yaml"

# Keep an existing local control plane and its credentials intact.
EXISTING_RELEASE=$(run_helm list --deployed --failed --pending --uninstalling --namespace argocd --filter '^argocd$' -q)
if [ "$EXISTING_RELEASE" = "argocd" ]; then
  echo "Using existing Argo CD release argocd in argocd"
else
  umask 077
  VALUES_FILE=$(mktemp)
  trap 'rm -f "$VALUES_FILE"' EXIT

  ARGOCD_PASSWORD=$(aws ssm get-parameter --name /k8s/common/argocd-password --with-decryption --query Parameter.Value --output text)
  ARGOCD_MTIME=$(aws ssm get-parameter --name /k8s/common/argocd-mtime --with-decryption --query Parameter.Value --output text)

  export ARGOCD_PASSWORD ARGOCD_MTIME

  # Bootstrap uses the generated local settings; existing releases are preserved.
  python3 - "${ROOT_DIR}/charts/argo-cd/local/values-local-demo.yaml" > "$VALUES_FILE" <<'PY'
import os
import sys
import yaml

with open(sys.argv[1]) as file:
    values = yaml.safe_load(file)["argo-cd"]
values["fullnameOverride"] = "argocd"
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

fi

python3 "${SCRIPT_DIR}/runtime.py" "$KUBE_CONTEXT" --check-argocd
run_kubectl apply -f "${SCRIPT_DIR}/projects.yaml"
run_kubectl apply -f "${ROOT_DIR}/addons-local.yaml"
# ExternalSecret admission must be available before registering dependent apps.
run_kubectl wait --for=create deployment/external-secrets-webhook -n addon-external-secrets --timeout=180s
run_kubectl rollout status deployment/external-secrets-webhook -n addon-external-secrets --timeout=180s
run_kubectl wait --for=create clustersecretstore/parameter-store --timeout=180s
run_kubectl wait --for=condition=Ready clustersecretstore/parameter-store --timeout=180s
run_kubectl apply -f "${DEMO_DIR}/apps-local.yaml"

echo "Argo CD: http://localhost:8080 (python3 install/local/connect.py --only argocd)"
echo "GitOps status: kubectl --context ${KUBE_CONTEXT} -n argocd get applications"
