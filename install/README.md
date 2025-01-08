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
> github 계정으로 인증학 위해 client id 와 client secret 을 저장 합니다.
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
export ARGOCD_SERVER_SECRET="REPLACE_ME" # random string
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

## Install aws-load-balancer-controller

> argocd 에 대한 alb 를 생성 하기 위해 aws-load-balancer-controller 를 설치 합니다.

* <https://github.com/kubernetes-sigs/aws-load-balancer-controller>

```bash
# helm repo add eks https://aws.github.io/eks-charts

# helm repo update
# helm search repo aws-load-balancer-controller

helm upgrade --install aws-load-balancer-controller-eks-demo eks/aws-load-balancer-controller -n addon-aws-load-balancer-controller --create-namespace -f aws-load-balancer-controller/values.yaml
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
