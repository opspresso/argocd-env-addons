#!/bin/bash

# 실행 로그 색상 (파이프/리다이렉트 시에는 비활성화)
if [ -t 1 ]; then
  C_STEP='\033[1;36m' # cyan  - 단계
  C_CMD='\033[0;33m'  # yellow - 실행 명령
  C_OK='\033[0;32m'   # green - 완료
  C_OFF='\033[0m'
else
  C_STEP='' C_CMD='' C_OK='' C_OFF=''
fi

step() { echo -e "\n${C_STEP}==> $*${C_OFF}"; }
ok() { echo -e "\n${C_OK}✔ $*${C_OFF}"; }

# 실행할 명령을 그대로 출력한 뒤 실행합니다.
run() {
  echo -e "${C_CMD}\$ $*${C_OFF}"
  "$@"
}

# Argo CD 의 서명 키(server.secretkey)와 mcp 계정의 API 토큰을 SSM 에 고정합니다.
# 키는 없을 때만 만들고, 토큰은 없거나 무효일 때만 발급하므로 매번 실행해도
# 됩니다. 클러스터를 다시 만들어도 같은 토큰이 그대로 통하므로 재설치에 별도
# 절차가 붙지 않습니다.
step "서명 키·mcp 토큰 확인"
run ./token.sh || exit 1

# values.yaml 로 values.output.yaml 을 새로 만듭니다.
# 이전 실행의 산출물을 그대로 쓰면 values.yaml 의 변경이 반영되지 않습니다.
step "values.output.yaml 생성"
run ./build.sh || exit 1

step "IngressClass 생성 (EKS Auto Mode ALB)"
run kubectl apply -f ingress-class.yaml

step "external-dns 설치"
run helm upgrade --install external-dns external-dns/external-dns -n addon-external-dns --create-namespace -f external-dns/values.yaml

step "Argo CD 설치"
run helm upgrade --install argocd argo/argo-cd -n argocd --create-namespace -f values.output.yaml

step "admin 계정 조회"
echo -e "${C_CMD}\$ aws ssm get-parameter --name /k8s/common/admin-user${C_OFF}"
export ADMIN_USERNAME=$(aws ssm get-parameter --name /k8s/common/admin-user --with-decryption | jq .Parameter.Value -r)
echo -e "${C_CMD}\$ aws ssm get-parameter --name /k8s/common/admin-password${C_OFF}"
export ADMIN_PASSWORD=$(aws ssm get-parameter --name /k8s/common/admin-password --with-decryption | jq .Parameter.Value -r)

step "Argo CD 로그인"
# 비밀번호가 로그에 남지 않도록 마스킹해서 출력합니다.
echo -e "${C_CMD}\$ argocd login argocd.demo.opspresso.com --grpc-web --skip-test-tls --username ${ADMIN_USERNAME} --password ****${C_OFF}"
argocd login argocd.demo.opspresso.com --grpc-web --skip-test-tls --username $ADMIN_USERNAME --password $ADMIN_PASSWORD

step "클러스터 등록"
run argocd cluster add eks-demo -y
run argocd cluster list

step "AppProject 생성"
run argocd proj create addons --allow-cluster-resource '*/*' --dest '*,*' --src '*'
run argocd proj create apps --allow-cluster-resource '*/*' --dest '*,*' --src '*'

step "addons 등록"
run kubectl apply -n argocd -f https://raw.githubusercontent.com/opspresso/argocd-env-addons/main/addons.yaml

step "apps 등록"
run kubectl apply -n argocd -f https://raw.githubusercontent.com/opspresso/argocd-env-demo/main/apps.yaml

ok "https://argocd.demo.opspresso.com"
