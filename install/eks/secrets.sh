#!/bin/bash

# addons 가 읽는 무작위 값(비밀번호, OIDC client secret, 암호화 키, 내부 TLS)을 SSM 에 만듭니다.
# 없는 파라미터만 만들고 **있는 값은 절대 바꾸지 않습니다**. 바꾸면 DB 비밀번호·암호화된
# 데이터·발급된 세션이 맞지 않게 됩니다. install.sh 가 매번 호출해도 안전합니다.
#
# 사람이 넣어야 하는 값(GitHub OAuth App, Slack bot token 등)은 README 'Set variables' 와
# 각 chart README 를 따릅니다. 이 스크립트는 그 값을 만들지 않습니다.
#
#   ./secrets.sh                # 기본 클러스터 eks-demo
#   ./secrets.sh --check        # 만들지 않고 없는 파라미터만 출력 (없으면 종료 코드 1)

set -euo pipefail

SHELL_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CLUSTER="${CLUSTER:-eks-demo}"
CHECK="false"
case "${1:-}" in
"") ;;
--check) CHECK="true" ;;
*)
  echo "알 수 없는 인자: $1" >&2
  exit 2
  ;;
esac

WORK_DIR=$(mktemp -d)
trap 'rm -rf "$WORK_DIR"' EXIT

if [ -t 1 ]; then
  C_STEP='\033[1;36m' C_CMD='\033[0;33m' C_OK='\033[0;32m' C_OFF='\033[0m'
else
  C_STEP='' C_CMD='' C_OK='' C_OFF=''
fi

step() { echo -e "\n${C_STEP}==> $*${C_OFF}"; }
ok() { echo -e "${C_OK}✔ $*${C_OFF}"; }

# 파라미터가 있으면 0, ParameterNotFound 면 1. 그 밖의 오류(권한·통신)는 중단합니다.
exists() {
  local status=0
  aws ssm get-parameter --name "$1" --output json >/dev/null 2>"${WORK_DIR}/error" || status=$?
  if [ "$status" -eq 0 ]; then
    return 0
  fi
  if grep -Fq '(ParameterNotFound)' "${WORK_DIR}/error"; then
    return 1
  fi
  echo "SSM 조회 실패: $1 (종료 코드 $status)" >&2
  exit "$status"
}

MISSING=()

# 덮어쓰지 않으므로, 확인과 저장 사이에 다른 설치가 먼저 만들면 그 값을 남깁니다.
create() {
  local name="$1" value="$2"
  if exists "$name"; then
    echo "  keep ${name}"
    return 0
  fi
  if [ "$CHECK" = "true" ]; then
    echo -e "${C_CMD}  miss ${name}${C_OFF}"
    MISSING+=("$name")
    return 0
  fi
  echo -e "${C_CMD}  put  ${name}${C_OFF}"
  if ! aws ssm put-parameter --name "$name" --value "$value" --type SecureString --output json >/dev/null 2>"${WORK_DIR}/error"; then
    if grep -Fq '(ParameterAlreadyExists)' "${WORK_DIR}/error"; then
      echo "  keep ${name} (다른 설치가 먼저 만들었습니다)"
      return 0
    fi
    echo "SSM 저장 실패: ${name}" >&2
    exit 1
  fi
}

# 영문 소문자·대문자·숫자 32자. 기호를 넣지 않아 URL·설정 파일에 그대로 쓸 수 있습니다.
random() { openssl rand -base64 48 | tr -dc 'A-Za-z0-9' | cut -c1-"${1:-32}"; }

step "OIDC client secret (Argo CD Dex 와 각 addon 이 같은 값을 읽습니다)"
for name in grafana gitlab jenkins harbor keep; do
  create "/k8s/common/${name}/oidc-client-secret" "$(random)"
done

step "GitLab"
create /k8s/common/gitlab/root-password "$(random)"
create /k8s/common/gitlab/postgres-password "$(random)"
create /k8s/common/gitlab/valkey-password "$(random)"

step "Harbor"
# Harbor 는 대문자·소문자·숫자가 모두 든 8~128자를 요구합니다.
create /k8s/common/harbor/admin-password "$(random 29)Aa1"
# 저장된 자격 증명을 암호화합니다. 정확히 16자여야 합니다.
create /k8s/common/harbor/secret-key "$(openssl rand -hex 8)"

step "Nexus"
create /k8s/common/nexus/admin-password "$(random)"

step "Keep"
create /k8s/common/keep/database-password "$(random)"
create /k8s/common/keep/nextauth-secret "$(openssl rand -hex 32)"
for name in grafana argocd alertmanager; do
  create "/k8s/common/keep/${name}-api-key" "$(openssl rand -hex 32)"
done

# kanidmd 는 HTTPS 만 받습니다. gateway 가 이 CA 로 서버 인증서를 검증합니다.
# CA 인증서는 charts/kanidm/values-template.yaml.j2 에도 있으므로, CA 를 새로 만들면
# 출력된 인증서로 그 값을 바꿔야 합니다.
step "Kanidm 내부 TLS"
if exists /k8s/common/kanidm/tls-chain; then
  echo "  keep /k8s/common/kanidm/tls-chain, tls-key, ca-crt, ca-key"
elif [ "$CHECK" = "true" ]; then
  echo -e "${C_CMD}  miss /k8s/common/kanidm/tls-chain${C_OFF}"
  MISSING+=(/k8s/common/kanidm/tls-chain)
else
  service="kanidm.addon-kanidm.svc.cluster.local"
  hostname=$(python3 - "${SHELL_DIR}/../../env/${CLUSTER}.yaml" <<'EOF'
import sys
import yaml

with open(sys.argv[1]) as stream:
    print(yaml.safe_load(stream)["kanidm"]["hostname"])
EOF
)
  (
    cd "$WORK_DIR"
    umask 077
    openssl ecparam -name prime256v1 -genkey -noout -out ca.key
    openssl req -x509 -new -key ca.key -sha256 -days 3650 -subj "/CN=kanidm internal CA/O=opspresso" \
      -addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,keyCertSign,cRLSign" -out ca.crt
    openssl ecparam -name prime256v1 -genkey -noout -out tls.key
    openssl req -new -key tls.key -subj "/CN=${service}" -out tls.csr
    printf 'basicConstraints=CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth\nsubjectAltName=DNS:%s,DNS:kanidm.addon-kanidm.svc,DNS:kanidm,DNS:%s\n' \
      "$service" "$hostname" >ext.cnf
    openssl x509 -req -in tls.csr -CA ca.crt -CAkey ca.key -CAcreateserial -days 3650 -sha256 -extfile ext.cnf -out tls.crt 2>/dev/null
    openssl verify -CAfile ca.crt tls.crt >/dev/null
    cat tls.crt ca.crt >chain.crt
  )
  create /k8s/common/kanidm/ca-key "file://${WORK_DIR}/ca.key"
  create /k8s/common/kanidm/ca-crt "file://${WORK_DIR}/ca.crt"
  create /k8s/common/kanidm/tls-key "file://${WORK_DIR}/tls.key"
  create /k8s/common/kanidm/tls-chain "file://${WORK_DIR}/chain.crt"
  echo "  새 CA 를 만들었습니다. charts/kanidm/values-template.yaml.j2 의 ca.crt 를 다음 인증서로 바꾸세요."
  cat "${WORK_DIR}/ca.crt"
fi

if [ "$CHECK" = "true" ] && [ "${#MISSING[@]}" -gt 0 ]; then
  echo "없는 파라미터 ${#MISSING[@]}개" >&2
  exit 1
fi

ok "addon 시크릿을 확인했습니다."
