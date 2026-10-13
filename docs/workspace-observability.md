# Workspace와 Agent 서비스 관측성

현재 운영 대상은 k3s alpha다. EKS의 Prometheus·kube-state-metrics 설정은 향후 클러스터를 위한
선언이다. `config/workspace-alerts.yaml`이 Forge Sandbox 실패·준비 지연·OOM·quota,
실행 노드 DiskPressure/Ready, Forge·Librio worker·Studio 관찰 worker 가용성 경보의 정본이다.
EKS는 이를 `prometheus-agent-platform-workloads` PrometheusRule로 렌더한다.

k3s의 전송 경로는 Alloy → Grafana Cloud다. `workspace-metrics`는
Pod·Node·ResourceQuota·Deployment만 list/watch하며, namespace 리소스는
`agent-studio`, `agent-librio`, `agent-forge`, `agent-forge-workspaces`에서 조회한다.
Forge 실행 Pod의 cAdvisor `service`는 `agent-forge-sandbox`다. VictoriaMetrics는 배포하지 않는다.

| 책임 | 지표·대상 |
| --- | --- |
| Studio 실행 정책·대화 | `agent_studio_active_execution_requests`: Studio Agent 실행만 집계 |
| Studio 원격 작업 관찰·대화 재개 | `agent-studio-workspace-worker` Deployment |
| Forge Sandbox·native 모델·checkpoint | `agent-forge`, `agent-forge-workspaces`, `agent_forge_active_model_requests` |
| Librio 문서·오디오 작업 | `agent-librio-worker`; 웹과 worker는 별도 metrics target |
| Memory 기억 저장·조회 | `agent-memory`; 별도 ingestion worker 없음 |

`Workspace Capacity` 대시보드는 Forge quota·Pod·CPU·메모리·native 모델 부하와
Studio 관찰 worker, Forge API/worker, Librio worker를 구분한다. 유지보수로 desired replicas를
0으로 둔 Deployment는 worker 장애로 알리지 않는다. 경보의 service·severity를 알림까지 보존한다.

Grafana Cloud ruler에는 배포 절차에서 같은 `config/workspace-alerts.yaml`의 groups를 등록한다.
GitOps 렌더와 PR은 Cloud 규칙을 게시하지 않는다. Cloud 반영 여부와 실제 수신 지표를 따로 확인한다.
서비스 실행은 외부 모니터링 연결 상태에 의존하지 않는다.

## 배포 전환과 운영 확인

- 신규 metrics token을 SSM과 receiver 앱에 먼저 연결한다. [Alloy 인증](../charts/alloy/README.md#인증)을 따른다.
- 기존 `agent-studio-workspaces`의 작업·Pod를 종료하고 소유권 이전을 확인한 뒤 기존 리소스를 정리한다.
  addons 변경으로 기존 namespace나 PVC를 삭제하지 않는다. 새 Sandbox RBAC·격리 정책은 앱 chart가 소유한다.
- `agent-forge-workspaces`의 Pod phase/reason, OOM, Pod quota 사용량과 신규 서비스의 `up=1`을 확인한다.
- EKS `workspaces` pool의 DiskPressure·Ready, kubelet image GC와 파일시스템 여유를 확인한다.
  기존 EKS DefaultDeny와 Alloy의 좁은 readiness·DNS·API·Loki 예외를 유지한다.
- Forge heartbeat·orphan 정리와 Studio 관찰 worker heartbeat를 각각 확인한다.
- 퇴거·노드 장애 뒤 Forge 작업이 `interrupted`로 바뀌고 불명확한 작업을 다시 실행하지 않는지 확인한다.
  새 요청은 마지막 성공한 checkpoint에서 복원한다.

격리된 Kubernetes 실행 검증은 Agent Forge의 `test:kubernetes`가 소유한다.
운영 장애 주입은 배포 검증과 별도로 조율한다.
