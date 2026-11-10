# Production addon 용량

운영 클러스터는 EKS `eks-demo`(Auto Mode)다. 기준 NodePool은 Graviton arm64 `m7g.xlarge` 2대이고,
동적 NodePool `general`과 `workspaces`가 추가 용량을 만든다.
addon 자원은 이 저장소, 앱·DB·Forge 실행 quota는
`argocd-env-apps`, Auto Mode NodePool은 `terraform-env-demo/demo/6-eks-node`가 관리한다.

## 자원 정책

EKS의 컨테이너·초기화 작업·Helm 테스트에는 CPU와 메모리 request, 메모리 limit을 둔다.
CPU limit은 격리나 명확한 실행 예산이 필요한 곳에만 둔다. `scripts/validate.py`가 실제 렌더를
검사하므로 upstream chart가 추가한 작업에도 같은 정책이 적용된다. local의 예약 제거 규칙은 별도다.
CI는 미배포 `backup/`도 검사한다. 보관 chart의 예산은 활성화 전 실제 부하로 다시 검증한다.
Atlantis의 upstream 테스트는 자원 옵션이 없어, 제한을 선언한 HTTP UI 테스트로 대체한다.

requests는 `eks-demo`에서 측정한 working set p95·CPU p95에 여유를 더한 값이다(2026-11-10까지 7일 구간).
memory limit은 7일 peak보다 충분히 크게 둔다. CPU 기반 HPA를 쓰는 workload는 목표 사용률이
의미를 갖도록 CPU request를 25~50m로 유지하고 메모리만 조정한다. 측정 기간이 짧은 workload(GitLab, LLDAP)는
줄이지 않고 7일 데이터가 쌓이면 "확장 확인" 기준으로 다시 검토한다.

| 구성 | requests CPU / memory | memory limit | 확장·운영 기준 |
| --- | --- | --- | --- |
| Argo controller | 200m / 2Gi | 5Gi | 전체 reconcile peak 3.4Gi, reconciliation 지연·메모리 관찰 |
| Argo repo-server | 100m / 384Mi | 1Gi | 2 replicas, PDB 1, Helm 렌더 peak 540Mi |
| Argo server | 10m / 128Mi | 256Mi | 2 replicas, PDB 1 |
| Argo application-set / Dex / Redis | 10m/64Mi, 5m/128Mi, 10m/32Mi | 128Mi / 256Mi / 128Mi | 실제 사용량·queue 지연에 따라 조정 |
| Argo notifications | 5m / 48Mi | 128Mi | `service.webhook.keep`으로 Keep에 전송 |
| Argo Workflows controller / server | 20m/128Mi, 10m/128Mi | 512Mi / 256Mi | 실행 workflow 수가 늘면 controller 메모리 확인 |
| metrics-server | 10m / 64Mi | 256Mi | 2 replicas, 다른 노드에 배치, PDB 1 |
| Prometheus adapter | 10m / 48Mi | 256Mi | 2 replicas, 다른 노드에 배치, PDB 1 |
| Prometheus | 100m / 2560Mi | 4Gi | working set p95 2.3Gi, 80Gi PVC, 10일·60GiB retention |
| Loki / rules sidecar | 25m/384Mi, 10m/96Mi | 1Gi / 256Mi | 50Gi PVC, 31일 retention |
| Grafana | 20m / 288Mi | 512Mi | RWO PVC·SQLite, Recreate 배포 |
| Alloy / reloader | 40m/128Mi, 5m/16Mi | 256Mi / 64Mi | 노드마다 1개 |
| node-exporter | 10m / 24Mi | 64Mi | 노드마다 1개 |
| Istiod / gateway | 25m/192Mi, 50m/160Mi | 512Mi / 512Mi | EKS에서 2~6 replicas, CPU HPA, `system-cluster-critical` |
| Istio sidecar | 10m / 64Mi | 256Mi | meshed Pod마다 1개 |
| external-secrets controller / webhook / cert-controller | 10m/96Mi, 5m/64Mi, 5m/96Mi | 256Mi / 128Mi / 128Mi | webhook 2 replicas·PDB 1. ExternalSecret 수가 늘면 controller 메모리 확인 |
| kro | 10m / 64Mi | 512Mi | 인스턴스·RGD 수가 늘면 메모리 확인 |
| ARC controller | 10m / 64Mi | 512Mi | runner 수가 늘면 메모리 확인 |
| ACK RDS / S3 / DynamoDB controller | 10m / 64Mi | 256Mi | chart schema가 CPU limit을 요구해 200m을 둔다 |
| GitLab webservice / sidekiq / gitaly | 300m/2560Mi, 300m/1500Mi, 100m/256Mi | 3Gi / 2560Mi / 1Gi | Puma worker 2개. 측정 3시간, 7일 뒤 재검토 |
| GitLab toolbox / PostgreSQL | 200m/768Mi, 100m/512Mi | 2Gi / 1Gi | `gitlab-admin-sync`가 10분마다 toolbox에서 `gitlab-rails` 실행 |
| Keep backend / frontend / DB | 150m/768Mi, 50m/256Mi, 20m/256Mi | 2Gi / 768Mi / 1Gi | 알림 유입량이 늘면 backend CPU 확인 |
| LLDAP | 10m / 32Mi | 128Mi | SQLite PVC, 1 replica |
| oauth2-proxy | 10m / 64Mi | 256Mi | 보호 대상이 생기면 다시 측정 |

Agent 앱의 requests·limits는 `argocd-env-apps`의 각 chart `values.yaml`이 소유한다. limit은 부하 시험
peak(48 동시 요청에서 Studio 1.1Gi, Memory 530Mi, Models 400Mi)보다 크게 둔다.

Prometheus는 API latency·SLO histogram을 유지하고 사용하지 않는 상세 요청 크기·watch bucket을
스크레이프에서 제외한다. 새 대시보드나 규칙이 이 지표를 요구하면 필터도 함께 검토한다.

## 확장 확인

Grafana의 `Workspace Capacity`는 Deployment owner가 없는 Sandbox Pod도 직접 조회한다.
Pod quota·phase·CPU·메모리·전용 노드·worker·웹 실행 부하를 함께 확인한다.
Workspace PrometheusRule의 firing·resolved 상태는 Alertmanager가 Keep으로 보낸다. 임계값과 대기 시간은
`config/workspace-alerts.yaml` 한 곳에서 평가한다.

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

Argo CD 자체도 EKS에서 자동 sync다. addon PR을 merge하면 Argo CD chart가 해당 revision으로 sync되는지 확인하고
controller·server·repo-server·알림 로그를 확인한다. 알림 시험을 위해 장애를 인위적으로 만들지 않는다.
