# akuity

* <https://akuity.io/>

```bash
argocd login opspresso.cd.akuity.cloud --grpc-web

argocd proj create addons [flags]
argocd proj create apps [flags]

argocd app create addons --repo https://github.com/opspresso/argocd-env-addons --path addons \
  --dest-namespace default --dest-server https://kubernetes.default.svc --directory-recurse

```
