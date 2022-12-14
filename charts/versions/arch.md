# multi architecture

name | image | amd64 | arm64
--- | --- | --- | ---
argo-rollouts | quay.io/argoproj/argo-rollouts | ✅ | ✅
argocd | quay.io/argoproj/argocd | ✅ | ✅
aws-ebs-csi-driver | public.ecr.aws/ebs-csi-driver/aws-ebs-csi-driver | ✅ | ✅
aws-efs-csi-driver | amazon/aws-efs-csi-driver | ✅ | ✅
aws-load-balancer-controller | 602401143452.dkr.ecr.us-west-2.amazonaws.com/amazon/aws-load-balancer-controller | ✅ | ✅
aws-node | 602401143452.dkr.ecr.ap-northeast-2.amazonaws.com/amazon-k8s-cni | ✅ | ✅
aws-node-termination-handler | public.ecr.aws/aws-ec2/aws-node-termination-handler | ✅ | ✅
cert-manager | quay.io/jetstack/cert-manager-controller | ✅ | ✅
cluster-autoscaler | k8s.gcr.io/autoscaling/cluster-autoscaler | ✅ | ✅
coredns | 602401143452.dkr.ecr.ap-northeast-2.amazonaws.com/eks/coredns | ✅ | ✅
cortex | quay.io/cortexproject/cortex | ✅ | ❌
crossplane | crossplane/crossplane | ✅ | ✅
datadog | gcr.io/datadoghq/agent | ✅ | ✅
dex | ghcr.io/dexidp/dex | ✅ | ✅
external-dns | k8s.gcr.io/external-dns/external-dns | ✅ | ✅
external-secrets | ghcr.io/external-secrets/external-secrets | ✅ | ✅
grafana | grafana/grafana | ✅ | ✅
ingress-nginx | quay.io/kubernetes-ingress-controller/nginx-ingress-controller | ✅ | ✅
istio pilot | gcr.io/istio-release/pilot | ✅ | ✅
istio proxyv2 | gcr.io/istio-release/proxyv2 | ✅ | ✅
jaeger | jaegertracing/jaeger-agent >= 1.24 | ✅ | ✅
kiali | quay.io/kiali/kiali | ✅ | ✅
kube-proxy | 602401143452.dkr.ecr.ap-northeast-2.amazonaws.com/eks/kube-proxy | ✅ | ✅
kube-state-metrics | registry.k8s.io/kube-state-metrics/kube-state-metrics | ✅ | ✅
kubernetes-dashboard | kubernetesui/dashboard | ✅ | ✅
loki | grafana/loki | ✅ | ✅
metrics-server | k8s.gcr.io/metrics-server-amd64 / k8s.gcr.io/metrics-server-arm64 | ✅ | ✅
prometheus | quay.io/prometheus/prometheus | ✅ | ✅
promtail | grafana/promtail | ✅ | ✅

## image list

```bash
kubectl get pods --all-namespaces -o jsonpath="{.items[*].spec.containers[*].image}" |\
  tr -s '[[:space:]]' '\n' | sort | uniq -c
```

```
   5 602401143452.dkr.ecr.ap-northeast-2.amazonaws.com/amazon-k8s-cni:v1.11.3-eksbuild.1
   2 602401143452.dkr.ecr.ap-northeast-2.amazonaws.com/eks/coredns:v1.8.7-eksbuild.3
   5 602401143452.dkr.ecr.ap-northeast-2.amazonaws.com/eks/kube-proxy:v1.24.6-minimal-eksbuild.1
   2 602401143452.dkr.ecr.us-west-2.amazonaws.com/amazon/aws-load-balancer-controller:v2.4.5
   2 argoproj/argosay:v2
   2 crossplane/crossplane:v1.5.1
   1 docker.io/bitnami/postgresql:11.14.0-debian-10-r28
   1 docker.io/bitnami/redis:7.0.4-debian-11-r7
   4 docker.io/grafana/promtail:2.7.0
   2 gcr.io/istio-release/pilot:1.15.3
   9 gcr.io/istio-release/proxyv2:1.15.3
   1 gcr.io/kubecost1/cost-model:prod-1.98.0
   1 gcr.io/kubecost1/frontend:prod-1.98.0
   4 gcr.io/kubecost1/kubecost-network-costs:v16.2
   1 ghcr.io/dexidp/dex:v2.35.3
   3 ghcr.io/external-secrets/external-secrets:v0.7.0
   1 ghcr.io/linki/chaoskube:v0.24.0
   1 grafana/grafana:9.3.1
   1 grafana/loki:2.6.1
   2 infracost/cloud-pricing-api:0.3.10
   1 infracost/infracost-atlantis:latest
   1 k8s.gcr.io/autoscaling/cluster-autoscaler:v1.23.0
   1 k8s.gcr.io/cpa/cluster-proportional-autoscaler:1.8.6
   1 k8s.gcr.io/external-dns/external-dns:v0.13.1
   1 k8s.gcr.io/metrics-server/metrics-server:v0.6.2
   1 k8s.gcr.io/pause:3.6
   2 k8s.gcr.io/sig-storage/csi-attacher:v3.4.0
   5 k8s.gcr.io/sig-storage/csi-node-driver-registrar:v2.5.1
   2 k8s.gcr.io/sig-storage/csi-provisioner:v3.1.0
   2 k8s.gcr.io/sig-storage/csi-resizer:v1.4.0
   7 k8s.gcr.io/sig-storage/livenessprobe:v2.6.0
   1 kubernetesui/dashboard:v2.7.0
   1 nalbam/random-quiz:v0.3.17
   1 nalbam/sample-grpc:v0.10.1
   5 nalbam/sample-node:v0.12.4
   1 public.ecr.aws/aws-ec2/aws-node-termination-handler:v1.18.1
   1 public.ecr.aws/docker/library/redis:7.0.5-alpine
   7 public.ecr.aws/ebs-csi-driver/aws-ebs-csi-driver:v1.13.0
   2 quay.io/argoproj/argo-events:v1.7.3
   1 quay.io/argoproj/argo-rollouts:v1.3.1
   7 quay.io/argoproj/argocd:v2.5.4
   1 quay.io/argoproj/argocli:v3.4.4
   2 quay.io/argoproj/argoexec:v3.4.4
   1 quay.io/argoproj/kubectl-argo-rollouts:v1.3.1
   1 quay.io/argoproj/workflow-controller:v3.4.4
   1 quay.io/jetstack/cert-manager-cainjector:v1.10.1
   1 quay.io/jetstack/cert-manager-controller:v1.10.1
   1 quay.io/jetstack/cert-manager-webhook:v1.10.1
   1 quay.io/oauth2-proxy/oauth2-proxy:v7.3.0
   1 quay.io/prometheus-operator/prometheus-config-reloader:v0.60.1
   1 quay.io/prometheus-operator/prometheus-operator:v0.60.1
   5 quay.io/prometheus/node-exporter:v1.5.0
   1 quay.io/prometheus/prometheus:v2.39.1
   1 registry.k8s.io/kube-state-metrics/kube-state-metrics:v2.7.0
```
