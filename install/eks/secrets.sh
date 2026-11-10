#!/bin/bash

# Argo CD 와 addons 가 읽는 값 중 여기서 만들 수 있는 것(관리자 계정, 비밀번호, OIDC client
# secret, 암호화 키)을 SSM 에 만듭니다. SSM 이 비어 있어도, 이미 값이 있어도 같은 명령으로
# 실행합니다. install.sh 가 매번 호출해도 안전합니다.
#
# - 없는 파라미터만 만들고 **있는 값은 바꾸지 않습니다**. 바꾸면 DB 비밀번호·암호화된
#   데이터·발급된 세션이 맞지 않게 됩니다.
# - 예외는 argocd-password 하나입니다. admin-password 의 bcrypt 해시이므로, 없거나
#   admin-password 와 맞지 않으면 다시 만들고 argocd-mtime 도 갱신합니다.
# - 밖에서 발급하는 값(GitHub App, Slack bot token)은 만들지 않습니다.
#   없으면 영향받는 기능과 함께 경고만 출력합니다 (README 'External values').
#
#   ./secrets.sh                # 없는 값을 만든다
#   ./secrets.sh --check        # 만들지 않고 없는 값만 출력 (만들 값이 없으면 0, 있으면 1)

set -euo pipefail

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
warn() { echo -e "${C_CMD}  warn $*${C_OFF}"; }


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

# 값을 출력합니다. ParameterNotFound 면 빈 문자열입니다. 그 밖의 오류는 중단합니다.
read_value() {
  local status=0 response
  response=$(aws ssm get-parameter --name "$1" --with-decryption --output json 2>"${WORK_DIR}/error") || status=$?
  if [ "$status" -ne 0 ]; then
    if grep -Fq '(ParameterNotFound)' "${WORK_DIR}/error"; then
      return 0
    fi
    echo "SSM 조회 실패: $1 (종료 코드 $status)" >&2
    exit "$status"
  fi
  printf '%s' "$response" | jq -r '.Parameter.Value // ""'
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

# bcrypt 는 python 의 bcrypt 로 계산합니다. 비밀번호는 인자가 아니라 환경 변수로 넘깁니다.
bcrypt_hash() {
  PASSWORD="$1" python3 -c 'import bcrypt, os, sys
digest = bcrypt.hashpw(os.environ["PASSWORD"].encode(), bcrypt.gensalt(10)).decode()
# Argo CD documents $2a$; $2b$ is the same algorithm.
sys.stdout.write("$2a$" + digest[4:])'
}

bcrypt_match() {
  PASSWORD="$1" HASH="$2" python3 -c 'import bcrypt, os, sys
sys.exit(0 if bcrypt.checkpw(os.environ["PASSWORD"].encode(), os.environ["HASH"].encode()) else 1)' 2>/dev/null
}

# 덮어쓰는 유일한 경우입니다: 파생값을 원본(admin-password)에 맞춥니다.
put_overwrite() {
  if [ "$CHECK" = "true" ]; then
    echo -e "${C_CMD}  miss $1 (다시 만들어야 합니다)${C_OFF}"
    MISSING+=("$1")
    return 0
  fi
  echo -e "${C_CMD}  put  $1${C_OFF}"
  aws ssm put-parameter --name "$1" --value "$2" --type SecureString --overwrite --output json >/dev/null 2>"${WORK_DIR}/error" || {
    echo "SSM 저장 실패: $1" >&2
    exit 1
  }
}

if ! python3 -c 'import bcrypt' >/dev/null 2>&1; then
  echo "bcrypt가 필요합니다. 저장소 루트에서 python3 -m pip install -r requirements/runtime.txt 로 설치하세요." >&2
  exit 1
fi

step "Argo CD 관리자 (LLDAP·Grafana 관리자와 같은 계정)"
create /k8s/common/admin-user admin
# 비밀번호를 정하고 싶으면 설치 전에 /k8s/common/admin-password 를 넣습니다.
create /k8s/common/admin-password "$(random 24)"

ADMIN_PASSWORD=$(read_value /k8s/common/admin-password)
ARGOCD_PASSWORD=$(read_value /k8s/common/argocd-password)
if [ -z "$ADMIN_PASSWORD" ]; then
  # --check 에서 admin-password 가 없으면 해시를 비교할 수 없습니다.
  echo -e "${C_CMD}  miss /k8s/common/argocd-password${C_OFF}"
  MISSING+=(/k8s/common/argocd-password)
elif [ -n "$ARGOCD_PASSWORD" ] && bcrypt_match "$ADMIN_PASSWORD" "$ARGOCD_PASSWORD"; then
  echo "  keep /k8s/common/argocd-password"
  create /k8s/common/argocd-mtime "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
elif [ -z "$ARGOCD_PASSWORD" ]; then
  create /k8s/common/argocd-password "$(bcrypt_hash "$ADMIN_PASSWORD")"
  create /k8s/common/argocd-mtime "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
else
  # 해시와 시각을 함께 바꿉니다. 시각이 바뀌면 Argo CD 가 이전 관리자 세션을 끊습니다.
  put_overwrite /k8s/common/argocd-password "$(bcrypt_hash "$ADMIN_PASSWORD")"
  put_overwrite /k8s/common/argocd-mtime "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
fi
unset ADMIN_PASSWORD ARGOCD_PASSWORD

step "Argo CD webhook"
create /k8s/common/argocd-webhook "$(random)"

step "OIDC client secret (Argo CD Dex 와 각 addon 이 같은 값을 읽습니다)"
create /k8s/common/argo-workflows-client-secret "$(random)"
create /k8s/common/oauth2-proxy-client-secret "$(random)"
for name in grafana gitlab jenkins keep; do
  create "/k8s/common/${name}/oidc-client-secret" "$(random)"
done

step "GitLab"
create /k8s/common/gitlab/root-password "$(random)"
create /k8s/common/gitlab/postgres-password "$(random)"
create /k8s/common/gitlab/valkey-password "$(random)"

step "oauth2-proxy"
# cookie 암호화 키는 16·24·32 byte 여야 합니다.
create /k8s/common/cookie-secret "$(random 32)"

step "Nexus"
create /k8s/common/nexus/admin-password "$(random)"

step "LLDAP"
create /k8s/common/lldap/jwt-secret "$(random)"
create /k8s/common/lldap/key-seed "$(random)"

step "Keep"
create /k8s/common/keep/database-password "$(random)"
create /k8s/common/keep/nextauth-secret "$(openssl rand -hex 32)"
for name in grafana argocd alertmanager; do
  create "/k8s/common/keep/${name}-api-key" "$(openssl rand -hex 32)"
done

# 밖에서 발급하는 값입니다. 없어도 설치는 계속되고, 표시한 기능만 동작하지 않습니다.
step "External values (만들지 않습니다)"
EXTERNAL=0
external() {
  local name="$1" feature="$2"
  if exists "$name"; then
    echo "  keep ${name}"
  else
    warn "${name} 없음: ${feature}"
    EXTERNAL=$((EXTERNAL + 1))
  fi
}
# GitHub 로그인은 꺼져 있습니다(charts/argo-cd). 다시 켜면 OAuth App 도 확인합니다.
# external "/k8s/<argocd.github.org>/argocd-github-id" "GitHub 로그인 (Dex connector github)"
# external "/k8s/<argocd.github.org>/argocd-github-secret" "GitHub 로그인 (Dex connector github)"
for name in app_id installation_id private_key; do
  external "/k8s/common/github/opspresso-arc/${name}" "GitHub Actions runner (arc-runners)"
done
external /k8s/common/keep/slack-bot-token "Keep 시작과 Slack 경보 (keep)"
if [ "$EXTERNAL" -gt 0 ]; then
  echo "  README 'External values' 의 명령으로 넣은 뒤 addon 을 다시 sync 합니다."
fi

if [ "$CHECK" = "true" ] && [ "${#MISSING[@]}" -gt 0 ]; then
  echo "없는 파라미터 ${#MISSING[@]}개" >&2
  exit 1
fi

ok "addon 시크릿을 확인했습니다."
