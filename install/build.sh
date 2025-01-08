#!/bin/bash

# variables
echo "변수를 설정합니다."

export ARGOCD_HOSTNAME=$(aws ssm get-parameter --name /k8s/common/argocd-hostname --with-decryption | jq .Parameter.Value -r)

export GITHUB_ORG=$(aws ssm get-parameter --name /k8s/common/github-org --with-decryption | jq .Parameter.Value -r)
export GITHUB_TEAM=$(aws ssm get-parameter --name /k8s/common/github-team --with-decryption | jq .Parameter.Value -r)

export ARGOCD_PASSWORD=$(aws ssm get-parameter --name /k8s/common/argocd-password --with-decryption | jq .Parameter.Value -r)
export ARGOCD_MTIME=$(aws ssm get-parameter --name /k8s/common/argocd-mtime --with-decryption | jq .Parameter.Value -r)
export ARGOCD_SERVER_SECRET=$(aws ssm get-parameter --name /k8s/common/argocd-server-secret --with-decryption | jq .Parameter.Value -r)
export ARGOCD_WEBHOOK=$(aws ssm get-parameter --name /k8s/common/argocd-webhook --with-decryption | jq .Parameter.Value -r)

export ARGOCD_GITHUB_ID=$(aws ssm get-parameter --name "/k8s/${GITHUB_ORG}/argocd-github-id" --with-decryption | jq .Parameter.Value -r)
export ARGOCD_GITHUB_SECRET=$(aws ssm get-parameter --name "/k8s/${GITHUB_ORG}/argocd-github-secret" --with-decryption | jq .Parameter.Value -r)

export AWS_ACM_CERT="$(aws acm list-certificates --query "CertificateSummaryList[?contains(DomainName, '${ARGOCD_HOSTNAME}')].CertificateArn | [0]" --output text)"

# replace values.yaml
echo "values.yaml 파일을 복사하고 변수를 치환합니다."

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

echo "values.output.yaml 파일이 생성되었습니다."
echo "helm upgrade --install argocd argo/argo-cd -n argocd --create-namespace -f values.output.yaml"
