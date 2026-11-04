#!/bin/bash

# Kanidm(charts/kanidm)의 관리 계정 비밀번호와 Dex client secret 을 SSM 에 고정합니다.
# addons 가 동기화되어 kanidm Pod 가 준비된 뒤 실행합니다. 여러 번 실행해도 안전합니다.
#
#   1. /k8s/common/kanidm/idm-admin-password   idm_admin 비밀번호
#   2. /k8s/common/kanidm/dex-client-secret    OAuth2 client dex 의 secret
#
# Kanidm 은 비밀번호를 정해서 넣는 방법이 없습니다. idm_admin 비밀번호는
# `kanidmd recover-account` 가 만들고, client secret 은 Kanidm 이 만듭니다.
# 그래서 이 스크립트는 SSM 값이 Kanidm 에서 통하는지 확인하고, 없거나 통하지
# 않을 때만 Kanidm 이 만든 값으로 SSM 을 바꿉니다.
#
# SSM 을 바꾸면 그 값을 읽는 Secret 을 바로 갱신합니다(ExternalSecret force-sync).
# Dex 는 시작할 때만 secret 을 읽으므로, client secret 이 바뀌면 Dex 를 재시작합니다.
#
#   ./kanidm.sh                              # 현재 kubectl context, env/eks-demo.yaml
#   KUBE_CONTEXT=eks-demo CLUSTER=eks-demo ./kanidm.sh

set -euo pipefail

SHELL_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CLUSTER="${CLUSTER:-eks-demo}"
NAMESPACE="addon-kanidm"
ADMIN_PARAM="/k8s/common/kanidm/idm-admin-password"
CLIENT_PARAM="/k8s/common/kanidm/dex-client-secret"
TOOLS_IMAGE="kanidm/tools:1.12.0"

# KUBE_CONTEXT 가 있으면 그 context 를, 없으면 현재 context 를 씁니다.
kubectl() { command kubectl ${KUBE_CONTEXT:+--context "$KUBE_CONTEXT"} "$@"; }

SSM_ERROR_FILE=$(mktemp)
trap 'rm -f "$SSM_ERROR_FILE"' EXIT

if [ -t 1 ]; then
  C_STEP='\033[1;36m' C_CMD='\033[0;33m' C_OK='\033[0;32m' C_OFF='\033[0m'
else
  C_STEP='' C_CMD='' C_OK='' C_OFF=''
fi

step() { echo -e "\n${C_STEP}==> $*${C_OFF}"; }
ok() { echo -e "${C_OK}✔ $*${C_OFF}"; }

# 값은 시크릿이므로 파라미터 이름만 출력합니다. ParameterNotFound 만 빈 값으로 처리합니다.
ssm() {
  local response status
  echo -e "${C_CMD}  ssm  ${1}${C_OFF}" >&2
  if response=$(aws ssm get-parameter --name "$1" --with-decryption --output json 2>"$SSM_ERROR_FILE"); then
    printf '%s' "$response" | jq -er '.Parameter.Value | select(type == "string" and length > 0)'
  else
    status=$?
    if grep -Fq '(ParameterNotFound)' "$SSM_ERROR_FILE"; then
      return 0
    fi
    echo "SSM 조회 실패: $1 (종료 코드 $status)" >&2
    return "$status"
  fi
}

put() {
  echo -e "${C_CMD}  put  ${1}${C_OFF}"
  aws ssm put-parameter --name "$1" --value "$2" --type SecureString --overwrite --output json | jq -er .Version >/dev/null
}

# env/<cluster>.yaml 의 kanidm.hostname 을 읽습니다.
HOSTNAME=$(python3 - "${SHELL_DIR}/../../env/${CLUSTER}.yaml" <<'EOF'
import sys
import yaml

with open(sys.argv[1]) as stream:
    print(yaml.safe_load(stream)["kanidm"]["hostname"])
EOF
)
KANIDM_URL="https://${HOSTNAME}"

# idm_admin 으로 로그인해 명령 하나를 실행합니다. 비밀번호는 Pod spec 이 아니라
# 표준 입력으로 넘깁니다. 로그인에 실패하면 0 이 아닌 값으로 끝납니다.
kanidm_cli() {
  local password="$1" command="$2"
  printf '%s\n' "$password" | kubectl -n "$NAMESPACE" run "kanidm-cli-$$-${RANDOM}" \
    --rm -i --quiet --restart=Never --image="$TOOLS_IMAGE" \
    --env="KANIDM_URL=${KANIDM_URL}" --env="KANIDM_NAME=idm_admin" \
    --command -- /bin/sh -c "IFS= read -r KANIDM_PASSWORD; export KANIDM_PASSWORD; kanidm login </dev/null >/dev/null && ${command}"
}

force_sync() {
  kubectl -n "$1" annotate externalsecret "$2" "force-sync=$(date +%s)" --overwrite >/dev/null
}

step "Kanidm 준비 확인 (${KANIDM_URL})"
kubectl -n "$NAMESPACE" rollout status deploy/kanidm --timeout=5m

step "idm_admin 비밀번호"
ADMIN_PASSWORD="$(ssm "$ADMIN_PARAM")"
if [ -n "$ADMIN_PASSWORD" ] && kanidm_cli "$ADMIN_PASSWORD" "true" >/dev/null 2>&1; then
  ok "SSM 값으로 로그인됩니다. (${ADMIN_PARAM})"
else
  echo "  SSM 값이 없거나 로그인되지 않습니다. 새 비밀번호를 만듭니다."
  ADMIN_PASSWORD="$(kubectl -n "$NAMESPACE" exec deploy/kanidm -- /sbin/kanidmd recover-account idm_admin -c /config/server.toml 2>&1 |
    grep -o 'new_password: "[^"]*"' | cut -d'"' -f2)"
  if [ -z "$ADMIN_PASSWORD" ]; then
    echo "recover-account 가 비밀번호를 출력하지 않았습니다." >&2
    exit 1
  fi
  put "$ADMIN_PARAM" "$ADMIN_PASSWORD"
  kanidm_cli "$ADMIN_PASSWORD" "true" >/dev/null
  force_sync "$NAMESPACE" kanidm-idm-admin
  ok "새 비밀번호를 저장했습니다. provisioning Job 은 다음 sync 부터 이 값을 씁니다."
fi

step "Dex client secret"
CLIENT_SECRET="$(kanidm_cli "$ADMIN_PASSWORD" "kanidm system oauth2 show-basic-secret dex" | tr -d '\r\n')"
if [ -z "$CLIENT_SECRET" ]; then
  echo "OAuth2 client dex 가 없습니다. Argo CD 에서 kanidm 을 sync 해 provisioning Job 을 먼저 실행하세요." >&2
  exit 1
fi
if [ "$(ssm "$CLIENT_PARAM")" = "$CLIENT_SECRET" ]; then
  ok "SSM 값이 Kanidm 과 같습니다. (${CLIENT_PARAM})"
else
  put "$CLIENT_PARAM" "$CLIENT_SECRET"
  # argocd-secret 이 새 값을 읽은 뒤 Dex 를 다시 시작합니다.
  force_sync argocd argocd-secret
  kubectl -n argocd wait externalsecret/argocd-secret --for=condition=Ready --timeout=2m >/dev/null
  kubectl -n argocd rollout restart deploy/argocd-dex-server
  kubectl -n argocd rollout status deploy/argocd-dex-server --timeout=5m
  ok "새 client secret 을 저장하고 Dex 를 재시작했습니다."
fi
