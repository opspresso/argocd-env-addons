#!/bin/bash

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)

ENV_FILE="${ROOT_DIR}/env/k3s-demo.yaml"
ARGOCD_HOSTNAME=$(awk '/^argocd:/{found=1; next} found && /^  hostname:/{print $2; exit}' "${ENV_FILE}")
VALUES_FILE=$(mktemp)
trap 'rm -f "${VALUES_FILE}"' EXIT
sed "s/ARGOCD_HOSTNAME/${ARGOCD_HOSTNAME}/g" "${SCRIPT_DIR}/values.yaml" > "${VALUES_FILE}"

if [ -z "${KUBECONFIG:-}" ] && [ -r /etc/rancher/k3s/k3s.yaml ]; then
  export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
fi

step() {
  echo
  echo "==> $*"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "필수 명령을 찾을 수 없습니다: $1" >&2
    exit 1
  }
}

require_command helm
require_command kubectl

step "Helm repository 등록"
helm repo add argo https://argoproj.github.io/argo-helm --force-update
helm repo add jetstack https://charts.jetstack.io --force-update
helm repo update

step "cert-manager 설치"
helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --set crds.enabled=true \
  --wait \
  --timeout 5m

step "Let's Encrypt ClusterIssuer 생성"
kubectl apply -f "${SCRIPT_DIR}/cluster-issuer.yaml"

step "Argo CD 설치"
helm upgrade --install argocd argo/argo-cd \
  --namespace argocd \
  --create-namespace \
  --values "${VALUES_FILE}"

step "Argo CD 준비 대기"
kubectl -n argocd rollout status deployment/argocd-server --timeout=5m

step "AppProject 생성"
kubectl apply -f "${SCRIPT_DIR}/projects.yaml"

step "k3s addons 등록"
kubectl apply -f "${ROOT_DIR}/addons-k3s.yaml"

cat <<'EOF'

설치가 완료되었습니다.

접속 주소: https://argocd.demo.opsp.dev

인증서 상태 확인:
  kubectl -n traefik-gateway get certificate traefik-gateway-tls
admin 비밀번호 확인:
  kubectl -n argocd get secret argocd-initial-admin-secret \
    -o jsonpath='{.data.password}' | base64 -d; echo
EOF
