# akuity

* <https://akuity.io/>

```bash
argocd login opspresso.cd.akuity.cloud --grpc-web

argocd proj create addons --allow-cluster-resource '*/*' --dest '*,*' --src '*'
argocd proj create apps --allow-cluster-resource '*/*' --dest '*,*' --src '*'

argocd app create addons --repo https://github.com/opspresso/argocd-env-addons --path addons \
  --dest-namespace argocd --dest-server https://kubernetes.default.svc --directory-recurse \
  --sync-policy automated --self-heal --sync-option Prune=true

argocd app create apps --repo https://github.com/opspresso/argocd-env-apps --path apps \
  --dest-namespace argocd --dest-server https://kubernetes.default.svc --directory-recurse \
  --sync-policy automated --self-heal --sync-option Prune=true

```
