# Production addon 용량

`eks-demo`는 production이다. addon 자원은 이 저장소, 앱·DB·Workspace quota는
`argocd-env-demo`, Auto Mode NodePool은 `terraform-env-demo/demo/6-eks-node`가 관리한다.

## 자원 정책

EKS의 컨테이너·초기화 작업·Helm 테스트에는 CPU와 메모리 request, 메모리 limit을 둔다.
CPU limit은 격리나 명확한 실행 예산이 필요한 곳에만 둔다. `scripts/validate.py`가 실제 렌더를
검사하므로 upstream chart가 추가한 작업에도 같은 정책이 적용된다. k3s/local의 예약 제거 규칙은 별도다.
CI는 미배포 `backup/`도 검사한다. 보관 chart의 예산은 활성화 전 실제 부하로 다시 검증한다.
Atlantis의 upstream 테스트는 자원 옵션이 없어, 제한을 선언한 HTTP UI 테스트로 대체한다.

| 구성 | requests CPU / memory | memory limit | 확장·운영 기준 |
| --- | --- | --- | --- |
| Argo controller | 250m / 1Gi | 2Gi | reconciliation 지연·메모리 관찰 |
| Argo repo-server | 250m / 256Mi | 1Gi | 2 replicas, Helm 생성 시 CPU burst 허용 |
| Argo server | 50m / 128Mi | 256Mi | 2 replicas |
| Argo application-set / Dex / Redis | 50m/128Mi, 25m/64Mi, 25m/64Mi | 256Mi / 128Mi / 256Mi | 실제 사용량·queue 지연에 따라 조정 |
| Argo notifications | 50m / 128Mi | 128Mi | `service.slack`과 기존 Secret의 `slack-token` 연결 |
| metrics-server | 50m / 128Mi | 512Mi | 2 replicas, 다른 노드에 배치, PDB 1 |
| Prometheus adapter | 50m / 128Mi | 256Mi | 2 replicas, 다른 노드에 배치, PDB 1 |
| Prometheus | 500m / 1Gi | 4Gi | 80Gi PVC, 10일·60GiB retention |
| Loki / rules sidecar | 250m/512Mi, 10m/96Mi | 1Gi / 256Mi | 50Gi PVC, 31일 retention |
| Grafana | 100m / 256Mi | 512Mi | RWO PVC·SQLite, Recreate 배포 |
| Alloy / reloader | 100m/128Mi, 10m/50Mi | 512Mi / 64Mi | 노드마다 1개 |
| node-exporter | 25m / 32Mi | 64Mi | 노드마다 1개 |
| Istiod / gateway | 100m / 128Mi | 512Mi / 1Gi | EKS에서 2~6 replicas, CPU HPA |
| external-dns / external-secrets | 각 chart의 기존 예산 | 각 chart의 기존 예산 | 낮은 정상 사용량의 순간값만으로 예약을 줄이지 않는다 |

Prometheus는 API latency·SLO histogram을 유지하고 사용하지 않는 상세 요청 크기·watch bucket을
스크레이프에서 제외한다. 새 대시보드나 규칙이 이 지표를 요구하면 필터도 함께 검토한다.

## 확장 확인

Grafana의 `Workspace Capacity`는 Deployment owner가 없는 Sandbox Pod도 직접 조회한다.
Pod quota·phase·CPU·메모리·전용 노드·worker·웹 실행 부하를 함께 확인한다.

1. 앱 HPA가 `ScalingActive=True`인지 확인한다. Studio는 일반 실행과 native Gateway 요청을 합친
   `agent_studio_active_execution_requests` 및 앱 컨테이너 CPU를 사용한다.
2. `metrics.k8s.io`와 `custom.metrics.k8s.io`가 모두 응답하고 exporter target이 `up`인지 확인한다.
3. workload별 24시간 CPU·메모리 p95와 7일 peak, OOM·재시작·throttling을 같이 본다.
   CPU throttling 비율은 전체 CPU 사용률과 다르므로 단독으로 limit을 올리지 않는다.
4. PVC 사용량과 증가율, Loki query/ingestion 지연, Prometheus head series·rule 평가 시간을 확인한다.
5. NodePool·AWS vCPU quota·subnet IP 여유도 함께 확인한다. Pod request만 늘려서는 노드 상한을 넘을 수 없다.

Grafana·Loki·Prometheus의 저장소는 현재 단일 인스턴스다. Node 교체 때 EBS 재연결 시간이 필요하다.
다중 인스턴스가 필요해지면 Grafana 외부 DB, Loki object storage, Prometheus HA/remote storage를
각각 설계한다. RWO 저장소를 공유한 채 replica 수만 올리지 않는다.

Argo CD 자체는 EKS에서 수동 sync다. addon PR 반영 후 Argo CD chart도 해당 revision으로 sync하고
controller·server·repo-server·알림 로그를 확인한다. Slack 전송 시험을 위해 장애를 인위적으로 만들지 않는다.
