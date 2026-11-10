# Alloy

EKS의 Pod 로그를 수집해 Loki로 전송합니다. Linux 노드의 `addon-alloy` namespace에
DaemonSet으로 배포하며, 수집 설정은 `values-template.yaml.j2`에서 관리합니다.

| 환경 | 배포 정의 | 수집 대상 | 전송 대상 |
| --- | --- | --- | --- |
| EKS | `addons/eks/alloy.yaml` | Pod 로그 | Loki |

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
`agent-forge-workspaces`의 격리 정책은 유지합니다. 노드 서브넷이나 Service CIDR을
변경하면 env의 허용 CIDR도 갱신합니다. 정책은 EKS Auto Mode의 Network Policy Controller와
`ApplicationNetworkPolicy` CRD가 필요합니다.
컨트롤러의 기본 차단·DNS 정책 동작은 [AWS 문서](https://docs.aws.amazon.com/eks/latest/userguide/auto-net-pol.html)를 따릅니다.

로그에는 `cluster`, `namespace`, `pod`, `container`, `app`, `job` 라벨을 붙입니다.
Grafana의 Loki 데이터소스에서 다음 쿼리로 확인합니다.

```logql
{cluster="eks-demo", namespace="agent-studio"}
```

## 적용과 확인

저장소 루트에서 실행합니다. 생성된 values는 직접 수정하지 않습니다.

```bash
./scripts/gen_values.py -p eks -r alloy
./scripts/validate.py -r alloy
```

Git에 반영하면 addons Application이 자동 동기화합니다.
로그 읽기 위치는 노드의 `/var/lib/alloy`에 유지됩니다.

```bash
kubectl --context eks-demo get application alloy-eks-demo -n argocd
kubectl --context eks-demo get daemonset,pods -n addon-alloy
kubectl --context eks-demo get applicationnetworkpolicies,policyendpoints -n addon-alloy
kubectl --context eks-demo logs -n addon-alloy daemonset/alloy -c alloy --tail=50
```

## EKS 관리형 CNI 로그

EKS Auto Mode의 network-policy-agent와 eBPF SDK는 호스트 프로세스다. Pod 로그 탐색으로 수집되지
않으므로 `/var/log/aws-routed-eni/`의 두 로그를 기존 읽기 전용 mount에서 수집한다. 오류·실패만
보존하고 `cluster`, `node`, `namespace`, `job`으로 조회한다. 대량 conntrack 정상 로그는 버린다.
`job="kube-system/aws-network-policy-agent"`의 `Failed to Attach Egress TC probe`를 Grafana가
5분 창으로 평가해 Keep으로 보낸다. Slack 메시지는 Keep이 보낸다(`charts/keep/README.md`).

`--disable-reporting`으로 외부 usage report를 중지한다. Loki 전송과 수집 상태 검사는 계속 동작한다.
