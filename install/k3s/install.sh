#!/bin/bash

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)

ENV_FILE="${ROOT_DIR}/env/k3s-demo.yaml"
ARGOCD_HOSTNAME=$(awk '/^argocd:/{found=1; next} found && /^  hostname:/{print $2; exit}' "${ENV_FILE}")
VALUES_FILE=$(mktemp)
trap 'rm -f "${VALUES_FILE}"' EXIT
sed "s/ARGOCD_HOSTNAME/${ARGOCD_HOSTNAME}/g" "${SCRIPT_DIR}/values.yaml" > "${VALUES_FILE}"

if [ -z "${KUBECONFIG:-}" ] && [ -f /etc/rancher/k3s/k3s.yaml ]; then
  export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
fi

KUBE_RUN=()

if [ -n "${KUBECONFIG:-}" ] && [ ! -r "${KUBECONFIG}" ]; then
  KUBE_RUN=(sudo env KUBECONFIG="${KUBECONFIG}")
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
require_command aws
require_command jq
require_command argocd

if [ "${#KUBE_RUN[@]}" -gt 0 ]; then
  require_command sudo
fi

run_kubectl() {
  "${KUBE_RUN[@]}" kubectl "$@"
}

run_helm() {
  "${KUBE_RUN[@]}" helm "$@"
}

step "SSM 관리자 계정 조회"
export ADMIN_USERNAME=$(aws ssm get-parameter --name /k8s/common/admin-user --with-decryption | jq .Parameter.Value -r)
export ADMIN_PASSWORD=$(aws ssm get-parameter --name /k8s/common/admin-password --with-decryption | jq .Parameter.Value -r)
export ARGOCD_PASSWORD=$(aws ssm get-parameter --name /k8s/common/argocd-password --with-decryption | jq .Parameter.Value -r)
export ARGOCD_MTIME=$(aws ssm get-parameter --name /k8s/common/argocd-mtime --with-decryption | jq .Parameter.Value -r)

step "Helm repository 등록"
run_helm repo add argo https://argoproj.github.io/argo-helm --force-update
run_helm repo add jetstack https://charts.jetstack.io --force-update
run_helm repo add opspresso https://opspresso.github.io/helm-charts/ --force-update
run_helm repo update

step "cert-manager 설치"
run_helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --set crds.enabled=true \
  --wait \
  --timeout 5m

step "Let's Encrypt ClusterIssuer 생성"
run_kubectl apply -f "${SCRIPT_DIR}/cluster-issuer.yaml"

step "Gateway API CRD 설치"
run_helm upgrade --install gateway-api-crds opspresso/gateway-api-crds \
  --version 1.6.1 \
  --namespace gateway-api-crds \
  --create-namespace \
  --wait \
  --timeout 5m

step "Argo CD 설치"
run_helm upgrade --install argocd argo/argo-cd \
  --namespace argocd \
  --create-namespace \
  --values "${VALUES_FILE}" \
  --set-string "configs.secret.argocdServerAdminPassword=${ARGOCD_PASSWORD}" \
  --set-string "configs.secret.argocdServerAdminPasswordMtime=${ARGOCD_MTIME}"

step "Argo CD 준비 대기"
run_kubectl -n argocd rollout status deployment/argocd-server --timeout=5m

step "AppProject 생성"
run_kubectl apply -f "${SCRIPT_DIR}/projects.yaml"

step "k3s addons 등록"
run_kubectl apply -f "${ROOT_DIR}/addons-k3s.yaml"

step "Legacy Argo CD Ingress 정리"
run_kubectl -n argocd delete ingress argocd-server --ignore-not-found

step "Argo CD 로그인"
argocd login "${ARGOCD_HOSTNAME}" \
  --grpc-web \
  --skip-test-tls \
  --username "${ADMIN_USERNAME}" \
  --password "${ADMIN_PASSWORD}"

cat <<'EOF'

설치가 완료되었습니다.

접속 주소: https://argocd.demo.opsp.dev

인증서 상태 확인:
  kubectl -n traefik-gateway get certificate traefik-gateway-tls
관리자 계정은 AWS SSM Parameter Store의 /k8s/common/admin-user, /k8s/common/admin-password를 사용합니다.
EOF
