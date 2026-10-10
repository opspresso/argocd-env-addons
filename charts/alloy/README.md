# Alloy

환경별로 다음 대상을 수집합니다. 모두 Linux 노드의 `addon-alloy` namespace에
DaemonSet으로 배포하며, 수집 설정은 `values-template.yaml.j2`에서 관리합니다.

| 환경 | 배포 정의 | 수집 대상 | 전송 대상 |
| --- | --- | --- | --- |
| EKS | `addons/eks/alloy.yaml` | Pod 로그 | Loki |
| k3s | `addons/k3s/alloy.yaml` | 호스트·컨테이너·앱 메트릭 | Grafana Cloud |

## EKS 로그

`eks-demo`의 모든 노드에서 해당 노드의 Pod만 탐색하고, 읽기 전용으로 마운트한
`/var/log/pods`의 CRI 로그를 수집합니다. RBAC는 Pod의 get/list/watch만 허용합니다.
노드의 `/var/lib/alloy`에 읽기 위치를 보관해 Pod 재시작 후 이어서 수집합니다.

`eks-demo`는 `env/eks-demo.yaml`의 `alloy_network_policy`로 EKS Auto Mode의
`ApplicationNetworkPolicy`를 생성합니다. `workspaces` NodeClass의 `DefaultDeny`는
Sandbox뿐 아니라 Alloy에도 적용되므로 다음 통신을 명시적으로 허용합니다.

- 노드 서브넷 → Alloy TCP 12345: kubelet readiness 검사
- Alloy → cluster DNS UDP/TCP 53, Kubernetes API Service TCP 443: Pod 탐색
- Alloy → `loki.hostname` TCP 80: Loki 로그 전송. DNS 정책이 로드밸런서 IP 변경을 추적합니다.

정책은 `addon-alloy`의 Alloy Pod만 선택합니다. 노드의 기본 차단과
`agent-studio-workspaces`의 격리 정책은 유지합니다. 노드 서브넷이나 Service CIDR을
변경하면 env의 허용 CIDR도 갱신합니다. 정책은 EKS Auto Mode의 Network Policy Controller와
`ApplicationNetworkPolicy` CRD가 필요하며, k3s에는 생성하지 않습니다.
컨트롤러의 기본 차단·DNS 정책 동작은 [AWS 문서](https://docs.aws.amazon.com/eks/latest/userguide/auto-net-pol.html)를 따릅니다.

로그에는 `cluster`, `namespace`, `pod`, `container`, `app`, `job` 라벨을 붙입니다.
Grafana의 Loki 데이터소스에서 다음 쿼리로 확인합니다.

```logql
{cluster="eks-demo", namespace="agent-studio"}
```

## k3s 메트릭

연결 정보는 `env/k3s-demo.yaml`의 `grafana_cloud`에서 읽습니다.
호스트 메트릭 수집에 필요한 `/proc`, `/sys`, 호스트 루트는 읽기 전용으로 마운트하고,
host network를 사용합니다. CPU·메모리 requests/limits와 시스템 우선순위는 지정하지 않습니다.
현재 k3s 환경에는 Loki 전송 대상이 없어 로그를 수집하지 않습니다.

## 수집 대상

| 대상 | job | 주기 |
| --- | --- | --- |
| 호스트 | `integrations/node_exporter` | 15초 |
| kubelet | `kubelet` | 30초 |
| 컨테이너 | `integrations/cadvisor` | 15초 |
| Agent Studio | `agent-studio` | 15초 |
| Agent Memory | `agent-memory` | 15초 |

호스트와 앱의 `instance`는 클러스터 이름입니다. cAdvisor의 `service`는 workload
이름으로 맞춰 `../dockpad/grafana`의 Agent Platform 대시보드에서 조회할 수 있습니다.
앱 메트릭은 `/api/metrics`에서 수집하며 Agent Memory는 Bearer token을 사용합니다.
kubelet은 노드·실행 수·볼륨·runtime 상태를, cAdvisor는 대시보드의
CPU·메모리·네트워크·디스크 I/O·OOM 메트릭을 전송해 Cloud 시리즈 사용량을 제한합니다.
호스트와 앱 메트릭은 전체를 전송합니다.

## 인증

External Secrets가 `parameter-store` ClusterSecretStore를 통해 다음 SSM SecureString을
읽어 `alloy-grafana-cloud` Secret을 생성합니다. 토큰 값은 Git에 저장하지 않습니다.

- `/k8s/common/grafana-cloud/remote-write-api-key`: Grafana Cloud metrics write token
- `/k8s/<cluster>/agent-memory/metrics-bearer-token`: Agent Memory metrics token

`<cluster>`는 `env/<cluster>.yaml`의 `cluster`입니다. 기존 파라미터를 재사용하며,
노드 IAM 역할에는 해당 SSM 파라미터 읽기·복호화 권한이 필요합니다.
Secret을 환경변수로 읽으므로 토큰 교체 후 Alloy Pod를 재시작합니다.

## 적용과 확인

저장소 루트에서 실행합니다. 생성된 values는 직접 수정하지 않습니다.

```bash
./scripts/gen_values.py -p eks -r alloy
./scripts/gen_values.py -p k3s -r alloy
./scripts/validate.py -r alloy
```

Git에 반영하면 각 환경의 addons Application이 자동 동기화합니다.
EKS 로그 읽기 위치와 k3s 메트릭 WAL은 노드의 `/var/lib/alloy`에 유지됩니다.

```bash
kubectl --context eks-demo get application alloy-eks-demo -n argocd
kubectl --context eks-demo get daemonset,pods -n addon-alloy
kubectl --context eks-demo get applicationnetworkpolicies,policyendpoints -n addon-alloy
kubectl --context eks-demo logs -n addon-alloy daemonset/alloy -c alloy --tail=50

# Run against the k3s cluster.
kubectl get application alloy-k3s -n argocd
kubectl get pods,externalsecret -n addon-alloy
kubectl logs -n addon-alloy daemonset/alloy -c alloy --tail=50
```

k3s 메트릭은 Grafana Cloud 대시보드에서 `instance=k3s-demo`를 선택합니다.

## EKS 관리형 CNI 로그

EKS Auto Mode의 network-policy-agent와 eBPF SDK는 호스트 프로세스다. Pod 로그 탐색으로 수집되지
않으므로 `/var/log/aws-routed-eni/`의 두 로그를 기존 읽기 전용 mount에서 수집한다. 오류·실패만
보존하고 `cluster`, `node`, `namespace`, `job`으로 조회한다. 대량 conntrack 정상 로그는 버린다.
`job="kube-system/aws-network-policy-agent"`의 `Failed to Attach Egress TC probe`를 Grafana가
5분 창으로 평가해 기존 Slack contact point로 알린다. k3s에는 이 수집과 경보를 추가하지 않는다.

`--disable-reporting`으로 외부 usage report를 중지한다. Loki 전송과 수집 상태 검사는 계속 동작한다.

## VibeMon 인프라 요약

`env/<cluster>.yaml`의 `vibemon.enabled`로 같은 Argo CD Application에 독립적인
`vibemon-collector` Deployment를 추가합니다. Alloy의 로그·Grafana Cloud 경로는 그대로
동작합니다. 수집기는 기존 Metrics API를 읽으며, 새로운 node exporter나 TSDB를 설치하지
않습니다. CPU·메모리 사용률, 준비/전체 노드 수, 비정상 Pod 수만 VibeMon으로 전송합니다.
Pod 사양·로그·Kubernetes 자격 증명은 전송하지 않습니다.

배포 이미지는 공개 ECR의 AMD64/ARM64 digest로 고정합니다. root filesystem은 읽기 전용이며,
비특권 ServiceAccount에는 core nodes/pods list와 Metrics API nodes get/list만 허용합니다.
EKS는 CPU 25m·메모리 64Mi를 예약하고 메모리 상한은 192Mi입니다. k3s에는 저장소 정책에 따라
requests/limits를 설정하지 않습니다. Recreate 전략으로 같은 source ID의 수집기를 중복 실행하지
않습니다. readiness는 최근 120초 내 Web의 실제 수신 확인이 있어야 통과합니다. Web 장애 시
readiness만 실패하며 liveness로 재시작하지 않습니다.

대상 VibeMon 계정에서 write 토큰을 발급한 뒤, 해당 클러스터의 SSM SecureString
`/k8s/<cluster>/vibemon/write-token`에 저장합니다. External Secrets가 `addon-alloy` namespace의
`vibemon-collector` Secret으로 연결합니다. 토큰은 values·이미지·CLI 인자에 넣지 않습니다.
토큰 교체 후 `kubectl rollout restart deployment/vibemon-collector -n addon-alloy`로 반영합니다.

EKS의 별도 ApplicationNetworkPolicy는 이 Deployment만 선택하고 DNS, Kubernetes API와
설정한 `vibemon.hostname`의 HTTPS 송신만 허용합니다. 기존 Alloy 정책이나 노드 기본 차단은
완화하지 않습니다. k3s에는 EKS 전용 CRD를 생성하지 않습니다.

검증은 Argo의 Synced/Healthy와 Pod Ready뿐 아니라 같은 계정의 VibeMon `/api/v1/sources`에서
해당 source ID의 지표와 수신 시각이 계속 갱신되는지 확인해야 합니다. 프로세스가 실행 중이라는
사실만으로 정상 수집을 판단하지 않습니다. permanent HTTP 오류는 종료 코드 2로 표시되어
Kubernetes restart/backoff 상태에 나타납니다. Secret·origin·시간을 수정한 뒤 다시 시작합니다.
