#!/bin/bash

set -Eeuo pipefail

SHELL_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "${SHELL_DIR}"

HELM_TIMEOUT="${HELM_TIMEOUT:-10m}"
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


step "필수 명령 확인"
for command in aws jq kubectl helm openssl uuidgen python3; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "필수 명령을 찾을 수 없습니다: $command" >&2
    exit 1
  fi
done

if ! python3 -c 'import yaml' >/dev/null 2>&1; then
  echo "PyYAML이 필요합니다. 저장소 루트에서 python3 -m pip install -r requirements/runtime.txt 로 설치하세요." >&2
  exit 1
fi

step "Helm repository 등록"
run helm repo add argo https://argoproj.github.io/argo-helm --force-update
run helm repo update argo

step "SSM 접속 정보 조회"
ARGOCD_HOSTNAME=$(ssm /k8s/common/argocd-hostname)

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

step "Argo CD 설치"
run helm upgrade --install argocd argo/argo-cd -n argocd --create-namespace -f values.output.yaml --wait --timeout "$HELM_TIMEOUT"

# 공개 주소·로그인 없이 선언으로 등록합니다. 이 클러스터를 이름 eks-demo 로 등록하고
# addons·apps AppProject 를 만듭니다. ApplicationSet 은 destination name 으로 클러스터를 고릅니다.
step "클러스터·AppProject 등록"
run kubectl apply -n argocd -f bootstrap.yaml

step "addons 등록"
run kubectl apply -n argocd -f ../../addons-eks.yaml

step "apps 등록"
run kubectl apply -n argocd -f https://raw.githubusercontent.com/opspresso/argocd-env-apps/main/apps-eks.yaml

# 공개 주소는 istio addon 과 argo-cd addon 의 HTTPRoute 가 동기화된 뒤 응답합니다.
ok "Argo CD 설치 완료. addons 동기화 후 https://${ARGOCD_HOSTNAME}"
