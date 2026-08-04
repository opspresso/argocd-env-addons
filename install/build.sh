#!/bin/bash

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
# 로그는 stderr 로 보냅니다. stdout 은 $(...) 로 캡처되기 때문입니다.
ssm() {
  echo -e "${C_CMD}  ssm  ${1}${C_OFF}" >&2
  aws ssm get-parameter --name "$1" --with-decryption | jq .Parameter.Value -r
}

# 치환할 값도 시크릿이므로 플레이스홀더 이름만 출력합니다.
# 구분자($3)는 값에 / 가 들어가는 항목 때문에 항목별로 다릅니다.
sub() {
  echo -e "${C_CMD}  sed  ${1}${C_OFF}"
  find . -name values.output.yaml -exec sed -i "" -e "s${3}${1}${3}${2}${3}g" {} \;
}

# variables
step "SSM 파라미터 조회"

export ARGOCD_HOSTNAME=$(ssm /k8s/common/argocd-hostname)

export GITHUB_ORG=$(ssm /k8s/common/github-org)
export GITHUB_TEAM=$(ssm /k8s/common/github-team)

export ARGOCD_PASSWORD=$(ssm /k8s/common/argocd-password)
export ARGOCD_MTIME=$(ssm /k8s/common/argocd-mtime)
export ARGOCD_SERVER_SECRET=$(ssm /k8s/common/argocd-server-secret)
export ARGOCD_WEBHOOK=$(ssm /k8s/common/argocd-webhook)

# mcp 계정의 토큰 목록. ./token.sh 가 만들어 둡니다.
export ARGOCD_MCP_TOKENS=$(ssm /k8s/common/argocd-mcp-tokens)

export ARGOCD_GITHUB_ID=$(ssm "/k8s/${GITHUB_ORG}/argocd-github-id")
export ARGOCD_GITHUB_SECRET=$(ssm "/k8s/${GITHUB_ORG}/argocd-github-secret")

step "ACM 인증서 조회"
echo -e "${C_CMD}  acm  ${ARGOCD_HOSTNAME}${C_OFF}"

export AWS_ACM_CERT="$(aws acm list-certificates --query "CertificateSummaryList[?contains(DomainName, '${ARGOCD_HOSTNAME}')].CertificateArn | [0]" --output text)"

# replace values.yaml
step "values.yaml -> values.output.yaml 치환"
echo -e "${C_CMD}  cp   values.yaml values.output.yaml${C_OFF}"

cp values.yaml values.output.yaml

sub ARGOCD_HOSTNAME "${ARGOCD_HOSTNAME}" /
sub ARGOCD_PASSWORD "${ARGOCD_PASSWORD}" @
sub ARGOCD_MTIME "${ARGOCD_MTIME}" /
sub ARGOCD_SERVER_SECRET "${ARGOCD_SERVER_SECRET}" /
sub ARGOCD_MCP_TOKENS "${ARGOCD_MCP_TOKENS}" @
sub ARGOCD_GITHUB_ID "${ARGOCD_GITHUB_ID}" /
sub ARGOCD_GITHUB_SECRET "${ARGOCD_GITHUB_SECRET}" /
sub ARGOCD_WEBHOOK "${ARGOCD_WEBHOOK}" /
sub GITHUB_ORG "${GITHUB_ORG}" /
sub GITHUB_TEAM "${GITHUB_TEAM}" /
sub AWS_ACM_CERT "${AWS_ACM_CERT}" @

ok "values.output.yaml 파일이 생성되었습니다."

echo "helm upgrade --install argocd argo/argo-cd -n argocd --create-namespace -f values.output.yaml"
