# Workspace 관측성

EKS는 기존 Prometheus와 kube-state-metrics를 사용한다. `config/workspace-alerts.yaml`이
Pod 실패·준비 지연·OOM·quota, Workspace node의 DiskPressure/Ready, worker 가용성 경보의 정본이다.
렌더 과정에서 PrometheusRule로 전달하며 기존 node label allowlist가 `karpenter.sh/nodepool`을 제공한다.
EKS network policy controller는 `charts/eks-network-policy`가 이미 활성화한다.

k3s의 실제 전송 경로는 Alloy → Grafana Cloud다. `workspace-metrics`는 Pod·Node·ResourceQuota·Deployment만
읽는 kube-state-metrics이며 Pod/Deployment/Quota 조회 범위는 Agent Studio와 실행 namespace다.
Alloy는 필요한 상태 지표와 container filesystem 지표를 전송하고 실행 Pod의 service를
`agent-studio-sandbox`로 표시한다. Victoria Metrics chart는 이 경로에서 배포하지 않는다.

Grafana Cloud의 ruler에는 승인된 배포 절차에서 같은 `config/workspace-alerts.yaml`의 groups를 등록한다.
이 저장소의 PR 생성·Helm 렌더는 Cloud 설정을 게시하지 않는다. Cloud 경보 적용 여부는 배포 확인 항목이다.
필수 실행 경로는 외부 모니터링의 연결 상태에 의존하지 않는다.

## 운영 확인

- `agent-studio-workspaces`의 Pod phase/reason, OOM, Pod quota 사용량을 확인한다.
- EKS `workspaces` pool의 DiskPressure와 Ready, kubelet image GC와 파일시스템 여유 공간을 확인한다.
- worker heartbeat와 `Requested deletion of ... orphan Sandbox Pods` 로그를 확인한다.
- 퇴거/노드 장애 뒤 Workspace가 `interrupted`로 바뀌고 동일 작업을 재생하지 않는지 확인한다.
  새 요청은 마지막 성공한 체크포인트에서 복원되어야 한다.

로컬 일회용 k3s의 실제 디스크 퇴거·노드 재시작 시험은 Agent Studio의
`test:workspace:kubernetes`가 수행한다. 운영 장애 주입은 별도 승인 뒤 실행한다.
