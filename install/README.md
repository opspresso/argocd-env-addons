# argocd

* <https://argo-cd.readthedocs.io/en/stable/getting_started/>
* <https://argocd-applicationset.readthedocs.io/en/stable/Getting-Started/>

## create eks cluster

* <https://github.com/opspresso/terraform-env-demo/tree/main/demo/7-eks>

```bash
terraform apply
```

## generate values.yaml

> argocd admin password 를 잊어버리지 않기 위해, aws ssm 에 저장 합니다.
> github 계정으로 인증학 위해 client id 와 client secret 을 저장 합니다.
> github org (opspresso) 에 team (sre) 을 만들고 권한을 부여 합니다.

```bash
# variables
export ARGOCD_HOSTNAME="argocd.demo.opspresso.com"

export GITHUB_ORG="opspresso"
export GITHUB_TEAM="sre"

export ADMIN_PASSWORD="REPLACE_ME"
export ARGOCD_PASSWORD="$(htpasswd -nbBC 10 "" ${ADMIN_PASSWORD} | tr -d ':\n' | sed 's/$2y/$2a/')"
export ARGOCD_SERVER_SECRET="REPLACE_ME" # random string
export ARGOCD_WEBHOOK="REPLACE_ME" # random string
export ARGOCD_NOTI_TOKEN="REPLACE_ME" # xoxp-xxxx <https://api.slack.com/apps>

export ARGOCD_GITHUB_ID="REPLACE_ME" # github OAuth Apps <https://github.com/organizations/opspresso/settings/applications>
export ARGOCD_GITHUB_SECRET="REPLACE_ME" # github OAuth Apps

export GRAFANA_GITHUB_ID="REPLACE_ME" # github OAuth Apps <https://github.com/organizations/opspresso/settings/applications>
export GRAFANA_GITHUB_SECRET="REPLACE_ME" # github OAuth Apps

export AWS_ACM_CERT="arn:aws:acm:xxx:xxx:certificate/xxx"

# put aws ssm parameter store
aws ssm put-parameter --name /k8s/common/admin-password --value "${ADMIN_PASSWORD}" --type SecureString --overwrite | jq .
aws ssm put-parameter --name /k8s/common/argocd-password --value "${ARGOCD_PASSWORD}" --type SecureString --overwrite | jq .
aws ssm put-parameter --name /k8s/common/argocd-server-secret --value "${ARGOCD_SERVER_SECRET}" --type SecureString --overwrite | jq .
aws ssm put-parameter --name /k8s/common/argocd-webhook --value "${ARGOCD_WEBHOOK}" --type SecureString --overwrite | jq .
aws ssm put-parameter --name /k8s/common/argocd-noti-token --value "${ARGOCD_NOTI_TOKEN}" --type SecureString --overwrite | jq .

aws ssm put-parameter --name /k8s/${GITHUB_ORG}/argocd-github-id --value "${ARGOCD_GITHUB_ID}" --type SecureString --overwrite | jq .
aws ssm put-parameter --name /k8s/${GITHUB_ORG}/argocd-github-secret --value "${ARGOCD_GITHUB_SECRET}" --type SecureString --overwrite | jq .

aws ssm put-parameter --name /k8s/${GITHUB_ORG}/grafana-github-id --value "${GRAFANA_GITHUB_ID}" --type SecureString --overwrite | jq .
aws ssm put-parameter --name /k8s/${GITHUB_ORG}/grafana-github-secret --value "${GRAFANA_GITHUB_SECRET}" --type SecureString --overwrite | jq .

# get aws ssm parameter store
export ADMIN_PASSWORD=$(aws ssm get-parameter --name /k8s/common/admin-password --with-decryption | jq .Parameter.Value -r)
export ARGOCD_PASSWORD=$(aws ssm get-parameter --name /k8s/common/argocd-password --with-decryption | jq .Parameter.Value -r)
export ARGOCD_MTIME="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
export ARGOCD_SERVER_SECRET=$(aws ssm get-parameter --name /k8s/common/argocd-server-secret --with-decryption | jq .Parameter.Value -r)
export ARGOCD_WEBHOOK=$(aws ssm get-parameter --name /k8s/common/argocd-webhook --with-decryption | jq .Parameter.Value -r)
export ARGOCD_NOTI_TOKEN=$(aws ssm get-parameter --name /k8s/common/argocd-noti-token --with-decryption | jq .Parameter.Value -r)
export ARGOCD_GITHUB_ID=$(aws ssm get-parameter --name /k8s/common/argocd-github-id --with-decryption | jq .Parameter.Value -r)
export ARGOCD_GITHUB_SECRET=$(aws ssm get-parameter --name /k8s/common/argocd-github-secret --with-decryption | jq .Parameter.Value -r)

export AWS_ACM_CERT="$(aws acm list-certificates --query "CertificateSummaryList[].{CertificateArn:CertificateArn,DomainName:DomainName}[?contains(DomainName,'${ARGOCD_HOSTNAME}')] | [0].CertificateArn" | jq . -r)"

# replace values.yaml
cp values.yaml values.output.yaml
find . -name values.output.yaml -exec sed -i "" -e "s/ARGOCD_HOSTNAME/${ARGOCD_HOSTNAME}/g" {} \;
find . -name values.output.yaml -exec sed -i "" -e "s@ARGOCD_PASSWORD@${ARGOCD_PASSWORD}@g" {} \;
find . -name values.output.yaml -exec sed -i "" -e "s/ARGOCD_MTIME/${ARGOCD_MTIME}/g" {} \;
find . -name values.output.yaml -exec sed -i "" -e "s/ARGOCD_SERVER_SECRET/${ARGOCD_SERVER_SECRET}/g" {} \;
find . -name values.output.yaml -exec sed -i "" -e "s/ARGOCD_GITHUB_ID/${ARGOCD_GITHUB_ID}/g" {} \;
find . -name values.output.yaml -exec sed -i "" -e "s/ARGOCD_GITHUB_SECRET/${ARGOCD_GITHUB_SECRET}/g" {} \;
find . -name values.output.yaml -exec sed -i "" -e "s/ARGOCD_WEBHOOK/${ARGOCD_WEBHOOK}/g" {} \;
find . -name values.output.yaml -exec sed -i "" -e "s/GITHUB_ORG/${GITHUB_ORG}/g" {} \;
find . -name values.output.yaml -exec sed -i "" -e "s/GITHUB_TEAM/${GITHUB_TEAM}/g" {} \;
find . -name values.output.yaml -exec sed -i "" -e "s@AWS_ACM_CERT@${AWS_ACM_CERT}@g" {} \;
```

## Install Argo CD

> Argocd 를 설치 합니다.
> addons 를 위해 ApplicationSet 도 함께 설치 합니다.

```bash
# helm repo add argo https://argoproj.github.io/argo-helm

# helm repo update
# helm search repo argo-cd

helm upgrade --install argocd argo/argo-cd -n argocd --create-namespace -f values.output.yaml

# kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
```

## argocd-server

> aws 에 elb 가 생성 되었습니다. route53 에서 argocd.demo.opspresso.com 와 연결해 줍니다.

```bash
kubectl get pod -n argocd
kubectl get svc argocd-server -n argocd
```

NAME          | TYPE         | CLUSTER-IP    | EXTERNAL-IP                     | PORT(S)                    | AGE
------------- | ------------ | ------------- | ------------------------------- | -------------------------- | ---
argocd-server | LoadBalancer | 172.20.41.157 | xxx-000.apne2.elb.amazonaws.com | 80:30080/TCP,443:30443/TCP | 64m

* <https://ap-northeast-2.console.aws.amazon.com/ec2/v2/home?region=ap-northeast-2#LoadBalancers:>
* <https://console.aws.amazon.com/route53/v2/hostedzones>
* <https://argocd.demo.opspresso.com>

## see external-dns

* See <https://github.com/opspresso/argocd-env-addons/tree/main/install/external-dns>

```bash
# helm search repo external-dns

helm upgrade --install external-dns external-dns/external-dns \
  -n addon-external-dns --create-namespace \
  -f external-dns/values.yaml

POD_NAME=$(kubectl get pod -n addon-external-dns -o json | jq '.items[0].metadata.name' -r)
kubectl logs ${POD_NAME} -n addon-external-dns
```

## argocd login

> argocd 에 로그인 합니다.
> cluster 를 add 합니다.

```bash
export ADMIN_USERNAME="admin"
export ADMIN_PASSWORD=$(aws ssm get-parameter --name /k8s/common/admin-password --with-decryption | jq .Parameter.Value -r)

argocd login argocd.demo.opspresso.com --grpc-web --skip-test-tls --username $ADMIN_USERNAME --password $ADMIN_PASSWORD

argocd cluster list
argocd cluster add eks-demo -y

# argocd cluster add eks-demo-a -y
# argocd cluster add eks-demo-b -y

argocd proj create addons --allow-cluster-resource '*/*' --dest '*,*' --src '*'
argocd proj create apps --allow-cluster-resource '*/*' --dest '*,*' --src '*'
```

## addons

> addons 를 등록 합니다.

```bash
kubectl apply -n argocd -f https://raw.githubusercontent.com/opspresso/argocd-env-addons/main/addons.yaml
```

## 삭제

### service 및 aws elb 삭제

> service 를 삭제 하여, LoadBalancer 로 생성한 elb 를 삭제 합니다.

```bash
kubectl delete svc -n argocd argocd-server

# helm uninstall argocd -n argocd
# helm uninstall argocd-applicationset -n argocd

# kubectl delete ns argocd
```

### terraform destory

```bash
terraform destory
```
