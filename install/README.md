# argocd

* <https://argo-cd.readthedocs.io/en/stable/getting_started/>
* <https://argocd-applicationset.readthedocs.io/en/stable/Getting-Started/>

## Create eks cluster

* <https://github.com/opspresso/terraform-env-demo/tree/main/demo/7-eks>

```bash
terraform apply
```

## Set variables

> argocd admin password 를 잊어버리지 않기 위해, aws ssm 에 저장 합니다.
> github 계정으로 인증하기 위해 client id 와 client secret 을 저장 합니다.
> github org (opspresso) 에 team (sre) 을 만들고 권한을 부여 합니다.

```bash
# variables
export ARGOCD_HOSTNAME="argocd.demo.opspresso.com"

export GITHUB_ORG="opspresso"
export GITHUB_TEAM="sre"

export ADMIN_USERNAME="admin"
export ADMIN_PASSWORD="REPLACE_ME"

export ARGOCD_PASSWORD="$(htpasswd -nbBC 10 "" ${ADMIN_PASSWORD} | tr -d ':\n' | sed 's/$2y/$2a/')"
export ARGOCD_MTIME="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
export ARGOCD_SERVER_SECRET="REPLACE_ME" # random string. 아래 'Set server secret and mcp token' 참고
export ARGOCD_WEBHOOK="REPLACE_ME" # random string
export ARGOCD_NOTI_TOKEN="REPLACE_ME" # xoxp-xxxx <https://api.slack.com/apps>

export ARGOCD_GITHUB_ID="REPLACE_ME" # github OAuth Apps <https://github.com/organizations/opspresso/settings/applications>
export ARGOCD_GITHUB_SECRET="REPLACE_ME" # github OAuth Apps

export AWS_ACM_CERT="arn:aws:acm:xxx:xxx:certificate/xxx"

# put aws ssm parameter store
aws ssm put-parameter --name /k8s/common/argocd-hostname --value "${ARGOCD_HOSTNAME}" --type SecureString --overwrite | jq .

aws ssm put-parameter --name /k8s/common/github-org --value "${GITHUB_ORG}" --type SecureString --overwrite | jq .
aws ssm put-parameter --name /k8s/common/github-team --value "${GITHUB_TEAM}" --type SecureString --overwrite | jq .

aws ssm put-parameter --name /k8s/common/admin-user --value "${ADMIN_USERNAME}" --type SecureString --overwrite | jq .
aws ssm put-parameter --name /k8s/common/admin-password --value "${ADMIN_PASSWORD}" --type SecureString --overwrite | jq .

aws ssm put-parameter --name /k8s/common/argocd-password --value "${ARGOCD_PASSWORD}" --type SecureString --overwrite | jq .
aws ssm put-parameter --name /k8s/common/argocd-mtime --value "${ARGOCD_MTIME}" --type SecureString --overwrite | jq .
aws ssm put-parameter --name /k8s/common/argocd-server-secret --value "${ARGOCD_SERVER_SECRET}" --type SecureString --overwrite | jq .
aws ssm put-parameter --name /k8s/common/argocd-webhook --value "${ARGOCD_WEBHOOK}" --type SecureString --overwrite | jq .
aws ssm put-parameter --name /k8s/common/argocd-noti-token --value "${ARGOCD_NOTI_TOKEN}" --type SecureString --overwrite | jq .

aws ssm put-parameter --name /k8s/common/argo-workflows-client-secret --value "${ARGOCD_SERVER_SECRET}" --type SecureString --overwrite | jq .
aws ssm put-parameter --name /k8s/common/oauth2-proxy-client-secret --value "${ARGOCD_SERVER_SECRET}" --type SecureString --overwrite | jq .
aws ssm put-parameter --name /k8s/common/cookie-secret --value "${ARGOCD_SERVER_SECRET}" --type SecureString --overwrite | jq .

aws ssm put-parameter --name /k8s/${GITHUB_ORG}/argocd-github-id --value "${ARGOCD_GITHUB_ID}" --type SecureString --overwrite | jq .
aws ssm put-parameter --name /k8s/${GITHUB_ORG}/argocd-github-secret --value "${ARGOCD_GITHUB_SECRET}" --type SecureString --overwrite | jq .
```

## Set server secret and mcp token

> 위 'Set variables' **다음에** 실행 합니다. `install.sh` 가 자동으로 실행 하므로,
> 보통은 따로 실행할 일이 없습니다.

```bash
./token.sh            # 없거나 무효일 때만 발급 (여러 번 실행해도 안전)
./token.sh --rotate   # 토큰만 새로 발급. 이전 토큰은 즉시 무효
```

`token.sh` 가 만드는 파라미터는 세 개 입니다.

| 파라미터 | 읽는 곳 |
|---|---|
| `/k8s/common/argocd-server-secret` | argocd-secret 의 `server.secretkey` — **없을 때만** 만듭니다 (32 bytes, hex) |
| `/k8s/common/argocd-mcp-tokens` | argocd-secret 의 `accounts.mcp.tokens` — `install/values.yaml` 과 `charts/argo-cd` 의 ExternalSecret 양쪽 |
| `/k8s/common/mcp-argocd/argocd-api-token` | mcp-argocd 파드의 `ARGOCD_API_TOKEN` (argocd-env-demo) |

Argo CD 는 API 토큰을 자기 `server.secretkey` 로 서명 하고, `jti` 가 계정의 토큰
목록에 있는지까지 봅니다. 그 키와 목록을 함께 SSM 에 고정해 두면 클러스터를 다시
만들어도 **같은 토큰이 그대로 통하므로, 재설치에 토큰 발급 절차가 붙지 않습니다.**
`argocd account generate-token` 은 목록을 클러스터 안에만 남기기 때문에 쓰지 않습니다.

> **`argocd-server-secret` 은 이미 있으면 건드리지 않습니다.** 바꾸면 발급된 토큰과
> 로그인 세션이 모두 무효가 되기 때문입니다. 위 'Set variables' 를 돌렸다면 거기서
> 이미 만들어져 있고, 이 스크립트는 그대로 읽어 씁니다. 새 계정이라 건너뛰었다면
> 여기서 만들어 집니다 — 다만 같은 블록이 그 값으로 넣는
> `argo-workflows-client-secret`·`oauth2-proxy-client-secret`·`cookie-secret` 은
> 별개이므로 'Set variables' 를 마저 실행 해야 합니다.
>
> 반대로 'Set variables' 를 **나중에 다시** 돌리면 `argocd-server-secret` 이 새 값으로
> 덮이면서 mcp 토큰이 무효가 됩니다. 그때는 `./token.sh` 를 한 번 더 실행 하면
> 자동으로 다시 발급 됩니다.

## Install ingress-class

> EKS Auto Mode 의 내장 로드밸런싱이 ingress 를 처리 하도록 IngressClass 를 먼저 생성 합니다.

```bash
kubectl apply -f ingress-class.yaml
```

## Install Argo CD

> Argocd 를 설치 합니다.
> addons 를 위해 ApplicationSet 도 함께 설치 합니다.

```bash
# helm repo add argo https://argoproj.github.io/argo-helm

# helm repo update
# helm search repo argo-cd

./build.sh

helm upgrade --install argocd argo/argo-cd -n argocd --create-namespace -f values.output.yaml

# kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
```

## Install external-dns

> argocd 도메인을 연결 하기 위해 external-dns 를 설치 합니다.

* <https://github.com/kubernetes-sigs/external-dns>

```bash
# helm repo add external-dns https://kubernetes-sigs.github.io/external-dns

# helm repo update
# helm search repo external-dns

helm upgrade --install external-dns external-dns/external-dns -n addon-external-dns --create-namespace -f external-dns/values.yaml

POD_NAME=$(kubectl get pod -n addon-external-dns -o json | jq '.items[0].metadata.name' -r)
kubectl logs ${POD_NAME} -n addon-external-dns

# sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder
```

* <https://argocd.demo.opspresso.com>

## Login to argocd

> argocd 에 로그인 합니다.
> cluster 를 add 합니다.

```bash
export ADMIN_USERNAME=$(aws ssm get-parameter --name /k8s/common/admin-user --with-decryption | jq .Parameter.Value -r)
export ADMIN_PASSWORD=$(aws ssm get-parameter --name /k8s/common/admin-password --with-decryption | jq .Parameter.Value -r)

argocd login argocd.demo.opspresso.com --grpc-web --skip-test-tls --username $ADMIN_USERNAME --password $ADMIN_PASSWORD

argocd cluster list
argocd cluster add eks-demo -y

# argocd cluster add eks-demo-a -y
# argocd cluster add eks-demo-b -y

argocd proj create addons --allow-cluster-resource '*/*' --dest '*,*' --src '*'
argocd proj create apps --allow-cluster-resource '*/*' --dest '*,*' --src '*'
```

## Install addons

> addons 를 등록 합니다.

```bash
kubectl apply -n argocd -f https://raw.githubusercontent.com/opspresso/argocd-env-addons/main/addons.yaml
```

## Delete addons

### Delete ingress and aws alb

> ingress 를 삭제 하여, aws-load-balancer-controller 로 생성한 alb 를 삭제 합니다.

```bash
kubectl delete ingress -n argocd argocd-server
kubectl delete ingress -n addon-atlantis atlantis
```

### Delete eks cluster

```bash
terraform destory
```
