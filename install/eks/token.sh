#!/bin/bash

# Argo CD 의 서명 키와 API 계정(mcp, keep)의 토큰을 Secrets Manager 에 고정합니다. 실행 순서대로:
#
#   1. /k8s/common/argocd-server-secret        서명 키. 없을 때만 만듭니다
#   2. /k8s/common/argocd-<계정>-tokens         계정의 토큰 목록
#      그 토큰                                  mcp: /k8s/common/mcp-argocd/argocd-api-token (mcp-argocd)
#                                               keep: /k8s/common/keep/argocd-api-token (Keep argocd provider)
#
# 1 은 Argo CD 가 API 토큰과 로그인 세션을 서명하는 키(argocd-secret 의
# server.secretkey)입니다. **이미 있으면 절대 건드리지 않습니다** — 바꾸면 발급된
# 토큰과 세션이 전부 무효가 되기 때문입니다. 이미 있으면 그대로 읽어 씁니다.
#
# 2 를 `argocd account generate-token` 으로 만들지 않는 이유: 그 명령은 토큰 목록을
# 클러스터 안 argocd-secret 에만 남깁니다. 클러스터를 다시 만들면 목록이 사라지고,
# mcp-argocd 가 들고 있던 토큰은 이유도 안 보이는 401 이 됩니다.
#
# Argo CD 가 토큰을 받을 때 보는 것은 세 가지뿐입니다
# (argoproj/argo-cd util/session/sessionmanager.go).
#
#   a. server.secretkey 로 서명한 HS256 JWT
#   b. sub 가 "<계정>:apiKey" 이고 그 계정에 apiKey capability 가 있을 것
#   c. jti 가 accounts.<계정>.tokens 목록에 있을 것
#
# a 의 키와 c 의 목록이 모두 Secrets Manager 에 있으므로 토큰은 여기서 직접 서명해 고정할 수
# 있습니다. 그러면 재설치해도 같은 토큰이 그대로 통하고, 발급 절차가 없어집니다.
#
# 인자 없이 실행하면 이미 고정된 토큰을 검증만 하고 유효하면 아무것도 하지
# 않습니다. install.sh 가 매번 호출해도 안전합니다.
#
#   ./token.sh                  # mcp 계정. 없거나 무효일 때만 발급
#   ./token.sh --account keep   # keep 계정
#   ./token.sh --rotate         # 토큰만 새로 발급 (이전 토큰은 즉시 무효)
#
# --rotate 도 서명 키는 바꾸지 않습니다. 키까지 갈아야 한다면 시크릿을 직접 지운
# 뒤 실행하고, 그때는 다른 로그인 세션도 함께 끊긴다는 것을 감안하세요. 복구 기간이
# 남은 시크릿과 같은 이름으로는 만들 수 없으므로 --force-delete-without-recovery 로 지웁니다.

set -euo pipefail

ERROR_FILE=$(mktemp)
trap 'rm -f "$ERROR_FILE"' EXIT

ACCOUNT="mcp"
ROTATE="false"
while [ $# -gt 0 ]; do
  case "$1" in
  --rotate) ROTATE="true" ;;
  --account)
    ACCOUNT="${2:-}"
    shift
    ;;
  *)
    echo "알 수 없는 인자: $1" >&2
    exit 2
    ;;
  esac
  shift
done

SECRET_KEY_NAME="/k8s/common/argocd-server-secret"
TOKENS_NAME="/k8s/common/argocd-${ACCOUNT}-tokens"
# Each account's token lives where its consumer reads it. charts/argo-cd lists
# the same accounts in argocd-cm (accounts.<name>: apiKey) and argocd-secret.
case "$ACCOUNT" in
mcp) TOKEN_NAME="/k8s/common/mcp-argocd/argocd-api-token" ;;
keep) TOKEN_NAME="/k8s/common/keep/argocd-api-token" ;;
*)
  echo "지원하지 않는 계정: ${ACCOUNT} (mcp, keep)" >&2
  exit 2
  ;;
esac

# 실행 로그 색상 (파이프/리다이렉트 시에는 비활성화)
if [ -t 1 ]; then
  C_STEP='\033[1;36m' # cyan  - 단계
  C_CMD='\033[0;33m'  # yellow - 실행 내용
  C_OK='\033[0;32m'   # green - 완료
  C_OFF='\033[0m'
else
  C_STEP='' C_CMD='' C_OK='' C_OFF=''
fi

step() { echo -e "\n${C_STEP}==> $*${C_OFF}"; }
ok() { echo -e "${C_OK}✔ $*${C_OFF}"; }

# 값을 출력합니다. 없으면 빈 문자열입니다. 값은 시크릿이므로 이름만 로그에 남깁니다.
get() {
  local response value status
  echo -e "${C_CMD}  get  ${1}${C_OFF}" >&2
  if response=$(aws secretsmanager get-secret-value --secret-id "$1" --output json 2>"$ERROR_FILE"); then
    if ! value=$(printf '%s' "$response" | jq -er '.SecretString | select(type == "string" and length > 0)'); then
      echo "Secrets Manager 값이 비어 있거나 문자열이 아닙니다: $1" >&2
      return 1
    fi
    printf '%s' "$value"
  else
    status=$?
    if grep -Fq 'An error occurred (ResourceNotFoundException) when calling the GetSecretValue operation:' "$ERROR_FILE"; then
      return 0
    fi
    echo "Secrets Manager 조회 실패: $1 (종료 코드 $status)" >&2
    return "$status"
  fi
}

# 시크릿이 있으면 0, 없으면 1. 값은 읽지 않습니다. if 조건 안에서도 실패가 묻히지
# 않도록 그 밖의 오류(권한·통신)는 여기서 종료합니다.
exists() {
  local status=0
  aws secretsmanager describe-secret --secret-id "$1" --output json >/dev/null 2>"$ERROR_FILE" || status=$?
  if [ "$status" -eq 0 ]; then
    return 0
  fi
  if grep -Fq 'An error occurred (ResourceNotFoundException) when calling the DescribeSecret operation:' "$ERROR_FILE"; then
    return 1
  fi
  echo "Secrets Manager 조회 실패: $1 (종료 코드 $status)" >&2
  exit "$status"
}

# 기본은 만들기만 합니다. 이미 있으면 create-secret 이 ResourceExistsException 으로 실패합니다.
# --overwrite 이면 있는 시크릿에 새 버전을 넣고, 없으면 만듭니다.
put() {
  local name="$1" value="$2" mode="${3:-}"
  echo -e "${C_CMD}  put  ${name}${C_OFF}"
  if [ "$mode" = "--overwrite" ] && exists "$name"; then
    aws secretsmanager put-secret-value --secret-id "$name" --secret-string "$value" --output json | jq -er .VersionId
  else
    aws secretsmanager create-secret --name "$name" --secret-string "$value" --output json | jq -er .VersionId
  fi
}

# JWT 는 padding 없는 base64url 을 씁니다.
b64() { openssl base64 -A | tr '+/' '-_' | tr -d '='; }

b64d() {
  local s="${1//-/+}"
  s="${s//_/\/}"
  case $((${#s} % 4)) in
  2) s="${s}==" ;;
  3) s="${s}=" ;;
  esac
  printf '%s' "$s" | openssl base64 -d -A
}

sign() {
  printf '%s' "$1" | openssl dgst -sha256 -hmac "$2" -binary | b64
}

# 고정된 토큰이 지금의 server.secretkey 와 토큰 목록으로 통하는지 확인합니다.
# server.secretkey 를 로테이트했다면 여기서 걸려 자동으로 다시 발급됩니다.
verify() {
  local token="$1" tokens="$2" secret="$3"

  [ -n "$token" ] && [ "$token" != "None" ] || return 1
  [ -n "$tokens" ] && [ "$tokens" != "None" ] || return 1
  [ "$(printf '%s' "$token" | tr -cd '.' | wc -c)" -eq 2 ] || return 1

  local head body sig
  head="${token%%.*}"
  body="${token#*.}"
  sig="${body#*.}"
  body="${body%%.*}"

  [ "$sig" = "$(sign "${head}.${body}" "$secret")" ] || return 1

  local jti
  jti="$(b64d "$body" | jq -r '.jti')"
  printf '%s' "$tokens" | jq -e --arg id "$jti" 'any(.[]; .id == $id)' >/dev/null
}

step "Secrets Manager 조회"

SERVER_SECRET="$(get "$SECRET_KEY_NAME")"
STORED_TOKEN="$(get "$TOKEN_NAME")"
STORED_TOKENS="$(get "$TOKENS_NAME")"

if [ -z "${SERVER_SECRET}" ]; then
  step "${SECRET_KEY_NAME} 생성"

  SERVER_SECRET="$(openssl rand -hex 32)"
  # Do not overwrite a key created by another installer after our read.
  put "${SECRET_KEY_NAME}" "${SERVER_SECRET}" >/dev/null

  ok "새로 만들었습니다. (32 bytes, hex)"
fi

if [ "${ROTATE}" = "false" ] && verify "${STORED_TOKEN}" "${STORED_TOKENS}" "${SERVER_SECRET}"; then
  ok "이미 고정된 토큰이 유효합니다. (${TOKEN_NAME})"
  exit 0
fi

step "토큰 발급"

JTI="$(uuidgen | tr '[:upper:]' '[:lower:]')"
IAT="$(date +%s)"

# SessionManager.Create 가 쓰는 클레임 그대로에서 exp 만 뺐습니다. 만료가 없으므로
# 폐기는 목록에서 지우는 것(시크릿을 [] 로 되돌리기)으로 합니다.
HEADER="$(printf '%s' '{"alg":"HS256","typ":"JWT"}' | b64)"
CLAIMS="$(printf '{"iat":%s,"iss":"argocd","jti":"%s","nbf":%s,"sub":"%s:apiKey"}' "${IAT}" "${JTI}" "${IAT}" "${ACCOUNT}" | b64)"

TOKEN="${HEADER}.${CLAIMS}.$(sign "${HEADER}.${CLAIMS}" "${SERVER_SECRET}")"

# settings.Token 은 {"id","iat","exp,omitempty"} 로 직렬화됩니다. exp 는 넣지 않습니다.
TOKENS="$(jq -cn --arg id "${JTI}" --argjson iat "${IAT}" '[{id: $id, iat: $iat}]')"

step "Secrets Manager 저장"

put "${TOKENS_NAME}" "${TOKENS}" --overwrite >/dev/null
put "${TOKEN_NAME}" "${TOKEN}" --overwrite >/dev/null

step "검증"

if verify "$(get "${TOKEN_NAME}")" "$(get "${TOKENS_NAME}")" "${SERVER_SECRET}"; then
  echo "  jti  ${JTI}"
  echo "  iat  ${IAT}"
else
  echo "저장된 토큰이 검증에 실패했습니다." >&2
  exit 1
fi

ok "토큰을 고정했습니다. argocd 를 다시 설치해도 그대로 씁니다."
