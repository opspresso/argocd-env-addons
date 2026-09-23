#!/bin/bash

set -Eeuo pipefail

SHELL_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "${SHELL_DIR}"

HELM_TIMEOUT="${HELM_TIMEOUT:-10m}"
ARGOCD_READY_TIMEOUT="${ARGOCD_READY_TIMEOUT:-600}"
CURRENT_STEP="초기화"

# 실행 로그 색상 (파이프/리다이렉트 시에는 비활성화)
if [ -t 1 ]; then
  C_STEP='\033[1;36m' # cyan  - 단계
  C_CMD='\033[0;33m'  # yellow - 실행 명령
  C_OK='\033[0;32m'   # green - 완료
  C_OFF='\033[0m'
else
  C_STEP='' C_CMD='' C_OK='' C_OFF=''
fi

step() {
  CURRENT_STEP="$*"
  echo -e "\n${C_STEP}==> $*${C_OFF}"
}
ok() { echo -e "\n${C_OK}✔ $*${C_OFF}"; }

# 실패한 명령에는 비밀번호가 포함될 수 있으므로 단계와 종료 코드만 출력합니다.
trap 'status=$?; printf "\n오류: %s 단계 실패 (종료 코드 %s)\n" "$CURRENT_STEP" "$status" >&2; exit "$status"' ERR

# 실행할 명령을 그대로 출력한 뒤 실행합니다.
run() {
  echo -e "${C_CMD}\$ $*${C_OFF}"
  "$@"
}

ssm() {
  echo "  ssm  $1" >&2
  aws ssm get-parameter --name "$1" --with-decryption |
    jq -er '.Parameter.Value | select(type == "string" and length > 0)'
}

wait_for_argocd() {
  local deadline=$((SECONDS + ARGOCD_READY_TIMEOUT))
  local remaining request_timeout delay http_code

  # Pod 준비와 ALB 대상 등록·DNS 전파 완료 시점은 다를 수 있습니다.
  while [ "$SECONDS" -lt "$deadline" ]; do
    remaining=$((deadline - SECONDS))
    [ "$remaining" -gt 0 ] || break
    request_timeout=10
    [ "$remaining" -ge "$request_timeout" ] || request_timeout="$remaining"
    if http_code=$(curl --silent --show-error --output /dev/null \
      --write-out '%{http_code}' --connect-timeout 5 --max-time "$request_timeout" \
      "https://${ARGOCD_HOSTNAME}/healthz") && [ "$http_code" = "200" ]; then
      ok "Argo CD 접속 준비 완료"
      return 0
    fi

    echo "  Argo CD 접속 준비 중 (HTTP ${http_code:-000})"
    remaining=$((deadline - SECONDS))
    [ "$remaining" -gt 0 ] || break
    delay=5
    [ "$remaining" -ge "$delay" ] || delay="$remaining"
    sleep "$delay"
  done

  echo "Argo CD가 ${ARGOCD_READY_TIMEOUT}초 안에 준비되지 않았습니다. Pod·Ingress·ALB·DNS 상태를 확인하세요." >&2
  return 1
}

step "필수 명령 확인"
for command in aws jq kubectl helm argocd curl openssl uuidgen python3; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "필수 명령을 찾을 수 없습니다: $command" >&2
    exit 1
  fi
done

if ! [[ "$ARGOCD_READY_TIMEOUT" =~ ^[1-9][0-9]*$ ]]; then
  echo "ARGOCD_READY_TIMEOUT은 초 단위의 양의 정수여야 합니다." >&2
  exit 1
fi

if ! python3 -c 'import yaml' >/dev/null 2>&1; then
  echo "PyYAML이 필요합니다. 저장소 루트에서 python3 -m pip install -r requirements/runtime.txt 로 설치하세요." >&2
  exit 1
fi

step "Helm repository 등록"
run helm repo add argo https://argoproj.github.io/argo-helm --force-update
run helm repo add external-dns https://kubernetes-sigs.github.io/external-dns --force-update
run helm repo update argo external-dns

step "SSM 접속 정보 조회"
ARGOCD_HOSTNAME=$(ssm /k8s/common/argocd-hostname)
ADMIN_USERNAME=$(ssm /k8s/common/admin-user)
ADMIN_PASSWORD=$(ssm /k8s/common/admin-password)

# Argo CD 의 서명 키(server.secretkey)와 mcp 계정의 API 토큰을 SSM 에 고정합니다.
# 키는 없을 때만 만들고, 토큰은 없거나 무효일 때만 발급하므로 매번 실행해도
# 됩니다. 클러스터를 다시 만들어도 같은 토큰이 그대로 통하므로 재설치에 별도
# 절차가 붙지 않습니다.
step "서명 키·mcp 토큰 확인"
run ./token.sh

# values.yaml 로 values.output.yaml 을 새로 만듭니다.
# 이전 실행의 산출물을 그대로 쓰면 values.yaml 의 변경이 반영되지 않습니다.
step "values.output.yaml 생성"
run ./build.sh

step "IngressClass 생성 (EKS Auto Mode ALB)"
run kubectl apply -f ingress-class.yaml

step "external-dns 설치"
run helm upgrade --install external-dns external-dns/external-dns -n addon-external-dns --create-namespace -f external-dns/values.yaml --wait --timeout "$HELM_TIMEOUT"

step "Argo CD 설치"
run helm upgrade --install argocd argo/argo-cd -n argocd --create-namespace -f values.output.yaml --wait --timeout "$HELM_TIMEOUT"

step "Argo CD 접속 준비 대기"
wait_for_argocd

step "Argo CD 로그인"
# 비밀번호가 로그에 남지 않도록 마스킹해서 출력합니다.
echo -e "${C_CMD}\$ argocd login ${ARGOCD_HOSTNAME} --grpc-web --skip-test-tls --username ${ADMIN_USERNAME} --password ****${C_OFF}"
argocd login "$ARGOCD_HOSTNAME" --grpc-web --skip-test-tls --username "$ADMIN_USERNAME" --password "$ADMIN_PASSWORD"

step "클러스터 등록"
run argocd cluster add eks-demo -y
run argocd cluster list

step "AppProject 생성"
run argocd proj create addons --allow-cluster-resource '*/*' --dest '*,*' --src '*'
run argocd proj create apps --allow-cluster-resource '*/*' --dest '*,*' --src '*'

step "addons 등록"
run kubectl apply -n argocd -f https://raw.githubusercontent.com/opspresso/argocd-env-addons/main/addons-eks.yaml

step "apps 등록"
run kubectl apply -n argocd -f https://raw.githubusercontent.com/opspresso/argocd-env-demo/main/apps.yaml

ok "https://${ARGOCD_HOSTNAME}"
