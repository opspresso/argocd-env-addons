#!/bin/bash

helm upgrade --install argocd argo/argo-cd -n argocd --create-namespace -f values.output.yaml

helm upgrade --install external-dns external-dns/external-dns -n addon-external-dns --create-namespace -f external-dns/values.yaml

helm upgrade --install aws-load-balancer-controller-eks-demo eks/aws-load-balancer-controller -n addon-aws-load-balancer-controller --create-namespace -f aws-load-balancer-controller/values.yaml

export ADMIN_USERNAME=$(aws ssm get-parameter --name /k8s/common/admin-user --with-decryption | jq .Parameter.Value -r)
export ADMIN_PASSWORD=$(aws ssm get-parameter --name /k8s/common/admin-password --with-decryption | jq .Parameter.Value -r)

argocd login argocd.demo.opspresso.com --grpc-web --skip-test-tls --username $ADMIN_USERNAME --password $ADMIN_PASSWORD

argocd cluster add eks-demo -y
argocd cluster list

argocd proj create addons --allow-cluster-resource '*/*' --dest '*,*' --src '*'
argocd proj create apps --allow-cluster-resource '*/*' --dest '*,*' --src '*'

kubectl apply -n argocd -f https://raw.githubusercontent.com/opspresso/argocd-env-addons/main/addons.yaml

kubectl apply -n argocd -f https://raw.githubusercontent.com/opspresso/argocd-env-demo/main/apps.yaml
