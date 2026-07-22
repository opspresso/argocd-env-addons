# argocd-env-addons

* <https://argo-cd.readthedocs.io/en/stable/getting_started/>
* <https://argocd-applicationset.readthedocs.io/en/stable/Getting-Started/>

## see argocd

* See <https://github.com/opspresso/argocd-env-addons/tree/main/install/>

## gen chart

```bash
./gen_chart.py

./gen_chart.py -r cluster-autoscaler
```

## gen values

```bash
./gen_values.py

./gen_values.py -r cluster-autoscaler
```

## versions

<!--- BEGIN_VERSION --->
| NAME | | CURRENT | LATEST |
| --- | - | --- | --- |
| argo-cd | ✅ | 10.1.4 | 10.1.4 (v3.4.5) |
| argo-events |  |  | 2.4.23 (v1.9.11) |
| argo-rollouts | ✅ | 2.41.1 | 2.41.1 (v1.9.1) |
| argo-workflows | ✅ | 1.0.20 | 1.0.20 (v4.0.7) |
| atlantis | ✅ | 6.9.3 | 6.9.3 (v0.46.0) |
| cert-manager | ✅ | v1.21.0 | v1.21.0 (v1.21.0) |
| external-dns | ✅ | 1.21.1 | 1.21.1 (0.21.0) |
| external-secrets | ✅ | 2.8.0 | 2.8.0 (v2.8.0) |
| grafana | ✅ | 10.5.15 | 10.5.15 (12.3.1) |
| istio | ✅ | 1.30.3 | 1.30.3 (1.30.3) |
| karpenter |  |  | 1.14.0 (1.14.0) |
| loki-stack | ✅ | 2.10.3 | 2.10.3 (v2.9.3) |
| metrics-server | ✅ | 3.13.1 | 3.13.1 (0.8.1) |
| oauth2-proxy | ✅ | 10.7.0 | 10.7.0 (7.15.3) |
| prometheus-stack | ✅ | 87.19.0 | 87.19.0 (v0.92.1) |
| promtail | ✅ | 6.17.1 | 6.17.1 (3.5.1) |
| raw |  |  | 0.2.5 (0.2.3) |
<!--- END_VERSION --->
