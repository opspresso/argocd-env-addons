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
external-secrets | ghcr.io/external-secrets/kubernetes-external-secrets | ✅ | ✅
grafana | grafana/grafana | ✅ | ✅
ingress-nginx | quay.io/kubernetes-ingress-controller/nginx-ingress-controller | ✅ | ✅
irsa-operator | ghcr.io/voodooteam/irsa-operator | ✅ | ❌
istio pilot | gcr.io/istio-release/pilot | ✅ | ✅
istio proxyv2 | gcr.io/istio-release/proxyv2 | ✅ | ✅
jaeger | jaegertracing/jaeger-agent >= 1.24 | ✅ | ✅
kiali | quay.io/kiali/kiali | ✅ | ✅
kube-proxy | 602401143452.dkr.ecr.ap-northeast-2.amazonaws.com/eks/kube-proxy | ✅ | ✅
kube-state-metrics | k8s.gcr.io/kube-state-metrics/kube-state-metrics | ✅ | ✅
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
   4 602401143452.dkr.ecr.ap-northeast-2.amazonaws.com/amazon-k8s-cni:v1.10.3-eksbuild.1
   2 602401143452.dkr.ecr.ap-northeast-2.amazonaws.com/eks/coredns:v1.8.7-eksbuild.1
   4 602401143452.dkr.ecr.ap-northeast-2.amazonaws.com/eks/kube-proxy:v1.22.6-eksbuild.1
   2 602401143452.dkr.ecr.us-west-2.amazonaws.com/amazon/aws-load-balancer-controller:v2.4.2
   3 amazon/aws-cli:latest
   5 amazon/aws-efs-csi-driver:v1.4.0
   3 docker.io/grafana/promtail:2.4.2
   2 gcr.io/istio-release/pilot:1.14.2
   9 gcr.io/istio-release/proxyv2:1.14.2
   1 gcr.io/kubecost1/cost-model:prod-1.95.1
   1 gcr.io/kubecost1/frontend:prod-1.95.1
   3 gcr.io/kubecost1/kubecost-network-costs:v16.0
   1 ghcr.io/dexidp/dex:v2.30.2
   1 ghcr.io/engineer-man/piston:latest
   3 ghcr.io/external-secrets/external-secrets:v0.5.8
   1 ghcr.io/voodooteam/irsa-operator:v0.1.1
   1 grafana/grafana:9.0.4
   1 grafana/loki:2.5.0
   1 k8s.gcr.io/autoscaling/cluster-autoscaler:v1.23.0
   1 k8s.gcr.io/cpa/cluster-proportional-autoscaler:1.8.4
   1 k8s.gcr.io/external-dns/external-dns:v0.12.0
   1 k8s.gcr.io/kube-state-metrics/kube-state-metrics:v2.2.0
   1 k8s.gcr.io/metrics-server/metrics-server:v0.6.1
   1 k8s.gcr.io/pause:3.6
   2 k8s.gcr.io/sig-storage/csi-attacher:v3.4.0
   4 k8s.gcr.io/sig-storage/csi-node-driver-registrar:v2.5.1
   2 k8s.gcr.io/sig-storage/csi-provisioner:v3.1.0
   2 k8s.gcr.io/sig-storage/csi-resizer:v1.4.0
   6 k8s.gcr.io/sig-storage/livenessprobe:v2.6.0
   1 kubernetesui/dashboard:v2.6.0
   1 nalbam/sample-grpc:v0.10.1
   5 nalbam/sample-node:v0.11.3
   1 public.ecr.aws/aws-ec2/aws-node-termination-handler:v1.16.5
   1 public.ecr.aws/docker/library/redis:7.0.4-alpine
   6 public.ecr.aws/ebs-csi-driver/aws-ebs-csi-driver:v1.10.0
   2 public.ecr.aws/eks-distro/kubernetes-csi/external-provisioner:v2.1.1-eks-1-18-13
   5 public.ecr.aws/eks-distro/kubernetes-csi/livenessprobe:v2.2.0-eks-1-18-13
   3 public.ecr.aws/eks-distro/kubernetes-csi/node-driver-registrar:v2.1.0-eks-1-18-13
   2 quay.io/argoproj/argo-events:v1.7.1
   1 quay.io/argoproj/argo-rollouts:v1.2.0
   7 quay.io/argoproj/argocd:v2.4.7
   1 quay.io/argoproj/argocli:v3.3.8
   1 quay.io/argoproj/kubectl-argo-rollouts:v1.2.0
   1 quay.io/argoproj/workflow-controller:v3.3.8
   1 quay.io/jetstack/cert-manager-cainjector:v1.5.5
   1 quay.io/jetstack/cert-manager-controller:v1.5.5
   1 quay.io/jetstack/cert-manager-webhook:v1.5.5
   1 quay.io/prometheus-operator/prometheus-config-reloader:v0.50.0
   1 quay.io/prometheus-operator/prometheus-config-reloader:v0.57.0
   1 quay.io/prometheus-operator/prometheus-operator:v0.50.0
   1 quay.io/prometheus/alertmanager:v0.22.2
   4 quay.io/prometheus/node-exporter:v1.2.2
   1 quay.io/prometheus/prometheus:v2.28.1
   1 redis:alpine
```
