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
