#!/bin/bash

# Argo CD 의 서명 키와 mcp 계정의 API 토큰을 SSM 에 고정합니다. 실행 순서대로:
#
#   1. /k8s/common/argocd-server-secret        서명 키. 없을 때만 만듭니다
#   2. /k8s/common/argocd-mcp-tokens           mcp 계정의 토큰 목록
#      /k8s/common/mcp-argocd/argocd-api-token 그 토큰. mcp-argocd 가 씁니다
#
# 1 은 Argo CD 가 API 토큰과 로그인 세션을 서명하는 키(argocd-secret 의
# server.secretkey)입니다. **이미 있으면 절대 건드리지 않습니다** — 바꾸면 발급된
# 토큰과 세션이 전부 무효가 되기 때문입니다. README 의 'Set variables' 를 먼저
# 돌렸다면 그때 만들어져 있고, 이 스크립트는 그냥 읽어 씁니다.
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
# a 의 키와 c 의 목록이 모두 SSM 에 있으므로 토큰은 여기서 직접 서명해 고정할 수
# 있습니다. 그러면 재설치해도 같은 토큰이 그대로 통하고, 발급 절차가 없어집니다.
#
# 인자 없이 실행하면 이미 고정된 토큰을 검증만 하고 유효하면 아무것도 하지
# 않습니다. install.sh 가 매번 호출해도 안전합니다.
#
#   ./token.sh            # 없거나 무효일 때만 발급
#   ./token.sh --rotate   # 토큰만 새로 발급 (이전 토큰은 즉시 무효)
#
# --rotate 도 서명 키는 바꾸지 않습니다. 키까지 갈아야 한다면 파라미터를 직접 지운
# 뒤 실행하고, 그때는 다른 로그인 세션도 함께 끊긴다는 것을 감안하세요.

set -euo pipefail

ACCOUNT="mcp"

SECRET_KEY_PARAM="/k8s/common/argocd-server-secret"
TOKENS_PARAM="/k8s/common/argocd-mcp-tokens"
TOKEN_PARAM="/k8s/common/mcp-argocd/argocd-api-token"

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

# 조회한 값은 시크릿이므로 파라미터 이름만 출력합니다.
ssm() {
  echo -e "${C_CMD}  ssm  ${1}${C_OFF}" >&2
  aws ssm get-parameter --name "$1" --with-decryption 2>/dev/null | jq .Parameter.Value -r
}

put() {
  echo -e "${C_CMD}  put  ${1}${C_OFF}"
  aws ssm put-parameter --name "$1" --value "$2" --type SecureString --overwrite | jq .Version -r
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

ROTATE="false"
if [ "${1:-}" = "--rotate" ]; then
  ROTATE="true"
fi

step "SSM 파라미터 조회"

SERVER_SECRET="$(ssm ${SECRET_KEY_PARAM} || true)"

if [ -z "${SERVER_SECRET}" ] || [ "${SERVER_SECRET}" = "None" ]; then
  # hex 로 만드는 이유: build.sh 가 이 값을 sed 구분자 / 로 치환하기 때문에
  # base64 의 / 가 섞이면 values.output.yaml 이 깨집니다.
  step "${SECRET_KEY_PARAM} 생성"

  SERVER_SECRET="$(openssl rand -hex 32)"
  put "${SECRET_KEY_PARAM}" "${SERVER_SECRET}" >/dev/null

  ok "새로 만들었습니다. (32 bytes, hex)"
fi

STORED_TOKEN="$(ssm ${TOKEN_PARAM} || true)"
STORED_TOKENS="$(ssm ${TOKENS_PARAM} || true)"

if [ "${ROTATE}" = "false" ] && verify "${STORED_TOKEN}" "${STORED_TOKENS}" "${SERVER_SECRET}"; then
  ok "이미 고정된 토큰이 유효합니다. (${TOKEN_PARAM})"
  exit 0
fi

step "토큰 발급"

JTI="$(uuidgen | tr '[:upper:]' '[:lower:]')"
IAT="$(date +%s)"

# SessionManager.Create 가 쓰는 클레임 그대로에서 exp 만 뺐습니다. 만료가 없으므로
# 폐기는 목록에서 지우는 것(파라미터를 [] 로 되돌리기)으로 합니다.
HEADER="$(printf '%s' '{"alg":"HS256","typ":"JWT"}' | b64)"
CLAIMS="$(printf '{"iat":%s,"iss":"argocd","jti":"%s","nbf":%s,"sub":"%s:apiKey"}' "${IAT}" "${JTI}" "${IAT}" "${ACCOUNT}" | b64)"

TOKEN="${HEADER}.${CLAIMS}.$(sign "${HEADER}.${CLAIMS}" "${SERVER_SECRET}")"

# settings.Token 은 {"id","iat","exp,omitempty"} 로 직렬화됩니다. exp 는 넣지 않습니다.
TOKENS="$(jq -cn --arg id "${JTI}" --argjson iat "${IAT}" '[{id: $id, iat: $iat}]')"

step "SSM 파라미터 저장"

put "${TOKENS_PARAM}" "${TOKENS}" >/dev/null
put "${TOKEN_PARAM}" "${TOKEN}" >/dev/null

step "검증"

if verify "$(ssm ${TOKEN_PARAM})" "$(ssm ${TOKENS_PARAM})" "${SERVER_SECRET}"; then
  echo "  jti  ${JTI}"
  echo "  iat  ${IAT}"
else
  echo "저장된 토큰이 검증에 실패했습니다." >&2
  exit 1
fi

ok "토큰을 고정했습니다. argocd 를 다시 설치해도 그대로 씁니다."
