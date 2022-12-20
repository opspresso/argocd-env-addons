# akuity

* <https://akuity.io/>

## login admin

```bash
export ADMIN_USERNAME="admin"
export ADMIN_PASSWORD=$(aws ssm get-parameter --name /k8s/common/admin-password --with-decryption | jq .Parameter.Value -r)

argocd login opspresso.cd.akuity.cloud --grpc-web --username $ADMIN_USERNAME --password $ADMIN_PASSWORD

export CLUSTER="eks-demo"
```

## add cluster

* <https://akuity.cloud/opspresso/argocd/demo?tab=clusters>

```bash
ORG="" && TOKEN="xxxxxx" && \
  curl -s --cookie "organization=$ORG" -H "Authorization: Bearer $TOKEN" \
  "https://akuity.cloud/api/instances/clusters/xxxxxx/manifests" | \
  kubectl apply -f -
```

## add projects

```bash
argocd proj create addons --allow-cluster-resource '*/*' --dest '*,*' --src '*'
argocd proj create apps --allow-cluster-resource '*/*' --dest '*,*' --src '*'
```

## add addons

```bash
argocd app create addons --repo https://github.com/opspresso/argocd-env-addons --path addons \
  --dest-namespace argocd --dest-name $CLUSTER --directory-recurse --project addons \
  --sync-policy automated --self-heal --sync-option Prune=true
```

## add apps

```bash
argocd app create apps --repo https://github.com/opspresso/argocd-env-demo --path apps \
  --dest-namespace argocd --dest-name $CLUSTER --directory-recurse --project apps \
  --sync-policy automated --self-heal --sync-option Prune=true
```
