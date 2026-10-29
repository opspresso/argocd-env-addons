# Production addon 용량

운영 클러스터는 EKS `eks-demo`(Auto Mode)다. 기준 NodePool은 Graviton arm64 `m7g.xlarge` 2대이고,
동적 NodePool `general`과 `workspaces`가 추가 용량을 만든다. k3s 선언은 배포하지 않는다.
addon 자원은 이 저장소, 앱·DB·Forge 실행 quota는
`argocd-env-apps`, Auto Mode NodePool은 `terraform-env-demo/demo/6-eks-node`가 관리한다.

## 자원 정책

EKS의 컨테이너·초기화 작업·Helm 테스트에는 CPU와 메모리 request, 메모리 limit을 둔다.
CPU limit은 격리나 명확한 실행 예산이 필요한 곳에만 둔다. `scripts/validate.py`가 실제 렌더를
검사하므로 upstream chart가 추가한 작업에도 같은 정책이 적용된다. k3s/local의 예약 제거 규칙은 별도다.
CI는 미배포 `backup/`도 검사한다. 보관 chart의 예산은 활성화 전 실제 부하로 다시 검증한다.
Atlantis의 upstream 테스트는 자원 옵션이 없어, 제한을 선언한 HTTP UI 테스트로 대체한다.

requests는 `eks-demo`에서 측정한 working set·CPU peak에 여유를 더한 값이다(2026-10-27, 클러스터 기동 후
3시간 구간). memory limit은 peak보다 충분히 크게 둔다. CPU 기반 HPA를 쓰는 workload는 목표 사용률이
의미를 갖도록 CPU request를 25~50m로 유지한다. 7일 peak가 쌓이면 아래 "확장 확인" 기준으로 다시 검토한다.

| 구성 | requests CPU / memory | memory limit | 확장·운영 기준 |
| --- | --- | --- | --- |
| Argo controller | 100m / 768Mi | 2Gi | 초기 sync peak 1.1Gi, reconciliation 지연·메모리 관찰 |
| Argo repo-server | 50m / 256Mi | 1Gi | 2 replicas, PDB 1, Helm 생성 시 CPU burst 허용 |
| Argo server | 10m / 64Mi | 256Mi | 2 replicas, PDB 1 |
| Argo application-set / Dex / Redis | 10m/64Mi, 5m/48Mi, 10m/32Mi | 128Mi / 128Mi / 128Mi | 실제 사용량·queue 지연에 따라 조정 |
| Argo notifications | 5m / 48Mi | 128Mi | `service.slack`과 기존 Secret의 `slack-token` 연결 |
| metrics-server | 10m / 48Mi | 256Mi | 2 replicas, 다른 노드에 배치, PDB 1 |
| Prometheus adapter | 10m / 48Mi | 256Mi | 2 replicas, 다른 노드에 배치, PDB 1 |
| Prometheus | 50m / 1Gi | 3Gi | 80Gi PVC, 10일·60GiB retention |
| Loki / rules sidecar | 25m/192Mi, 5m/96Mi | 1Gi / 256Mi | 50Gi PVC, 31일 retention |
| Grafana | 20m / 160Mi | 512Mi | RWO PVC·SQLite, Recreate 배포 |
| Alloy / reloader | 20m/96Mi, 5m/16Mi | 256Mi / 64Mi | 노드마다 1개 |
| node-exporter | 10m / 24Mi | 64Mi | 노드마다 1개 |
| Istiod / gateway | 25m/128Mi, 50m/64Mi | 512Mi / 512Mi | EKS에서 2~6 replicas, CPU HPA, `system-cluster-critical` |
| Istio sidecar | 10m / 64Mi | 256Mi | meshed Pod마다 1개 |
| external-secrets controller / webhook / cert-controller | 10m/64Mi, 5m/64Mi, 5m/64Mi | 256Mi / 128Mi / 128Mi | webhook 2 replicas·PDB 1. ExternalSecret 수가 늘면 controller 메모리 확인 |
| kro | 50m / 128Mi | 512Mi | 측정 전 초기값. 인스턴스·RGD 수가 늘면 메모리 확인 |
| ACK RDS controller | 10m / 64Mi | 256Mi | 측정 전 초기값. chart schema가 CPU limit을 요구해 200m을 둔다 |
| ACK S3 controller | 10m / 64Mi | 256Mi | 측정 전 초기값. RDS controller와 같은 이유로 CPU limit 200m |
| ACK ElastiCache controller | 10m / 64Mi | 256Mi | 측정 전 초기값. RDS controller와 같은 이유로 CPU limit 200m |

Agent 앱의 requests·limits는 `argocd-env-apps`의 각 chart `values.yaml`이 소유한다. limit은 부하 시험
peak(48 동시 요청에서 Studio 1.1Gi, Memory 530Mi, Models 400Mi)보다 크게 둔다.

Prometheus는 API latency·SLO histogram을 유지하고 사용하지 않는 상세 요청 크기·watch bucket을
스크레이프에서 제외한다. 새 대시보드나 규칙이 이 지표를 요구하면 필터도 함께 검토한다.

k3s 선언은 Alloy가 필요한 지표만 Grafana Cloud로 전송한다. 공통 `retained_metrics` 필터는
`remote_write` 앞에 둔다. 전송 직전 필터만 사용하면 버릴 시계열도 WAL과 메모리 캐시에 들어간다.
필터 변경 시 Workspace 상태·디스크·앱 지표가 유지되고 remote write의 실패·대기 샘플이 늘지 않는지 확인한다.
k3s 선언의 `metrics.backend`는 `grafana-cloud`이며 로컬 metrics DB와 ServiceMonitor를 배포하지 않는다.
Alloy가 node·kubelet·Workspace 상태와 Studio·Memory·Knowledge·Forge의 metrics endpoint를 직접 수집한다.

## 확장 확인

Grafana의 `Workspace Capacity`는 Deployment owner가 없는 Sandbox Pod도 직접 조회한다.
Pod quota·phase·CPU·메모리·전용 노드·worker·웹 실행 부하를 함께 확인한다.
Workspace PrometheusRule의 firing 상태는 Grafana가 기존 Slack 경로로 전달한다. 임계값과 대기 시간은
`config/workspace-alerts.yaml` 한 곳에서 평가하며, Grafana는 `workspace_alert`와 severity label을 보존한다.

1. EKS 앱 HPA가 `ScalingActive=True`인지 확인한다. Studio는 Agent 실행만 집계한
   `agent_studio_active_execution_requests` 및 앱 컨테이너 CPU를 사용한다. Forge native 모델 요청은
   별도 `agent_forge_active_model_requests`로 관찰하며 Studio의 HPA 신호에 합치지 않는다.
2. `metrics.k8s.io`와 `custom.metrics.k8s.io`가 모두 응답하고 exporter target이 `up`인지 확인한다.
3. workload별 24시간 CPU·메모리 p95와 7일 peak, OOM·재시작·throttling을 같이 본다.
   CPU throttling 비율은 전체 CPU 사용률과 다르므로 단독으로 limit을 올리지 않는다.
4. PVC 사용량과 증가율, Loki query/ingestion 지연, Prometheus head series·rule 평가 시간을 확인한다.
5. NodePool·AWS vCPU quota·subnet IP 여유도 함께 확인한다. Pod request만 늘려서는 노드 상한을 넘을 수 없다.

`agent-forge-workspaces` quota는 0개까지 축소되는 전용 NodePool의 최대 용량을 나타내므로 현재 유휴 노드 용량과
비교하지 않는다. namespace quota overcommit 규칙에서는 이 namespace만 제외하고, 실제 Pod 요청의
N-1 여유·Workspace quota 사용률·Pending·Node 장애 규칙은 유지한다. 다른 namespace quota는 기존 기준으로 검사한다.

Grafana·Loki·Prometheus의 저장소는 현재 단일 인스턴스다. Node 교체 때 EBS 재연결 시간이 필요하다.
다중 인스턴스가 필요해지면 Grafana 외부 DB, Loki object storage, Prometheus HA/remote storage를
각각 설계한다. RWO 저장소를 공유한 채 replica 수만 올리지 않는다.

Argo CD 자체는 EKS에서 수동 sync다. addon PR 반영 후 Argo CD chart도 해당 revision으로 sync하고
controller·server·repo-server·알림 로그를 확인한다. Slack 전송 시험을 위해 장애를 인위적으로 만들지 않는다.
