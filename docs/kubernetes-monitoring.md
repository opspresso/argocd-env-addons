# Kubernetes monitoring

두 대시보드는 자원 예약량과 현재 사용량을 먼저 표시하며, 30초마다 갱신합니다.

- `kube-cluster`: 스케줄링 예약량 / allocatable, 실제 호스트 CPU·메모리·디스크 사용량, 노드 상태·압박·수집 실패, 노드별 상세와 추이 순서입니다. 호스트 사용량은 선택한 instance 중 최댓값으로, 평균에 가려지는 노드 과부하를 표시합니다.
- `kube-workload`: 선택한 워크로드의 CPU·메모리 사용량 / requests·limits 비율과 절대값, replica 가용성·Pod 장애·재시작·OOM, HTTP 오류, 컨테이너별 상세·트래픽·PVC·로그 순서입니다. requests·limits가 없거나 수집이 불완전하면 비율을 정상 0으로 표시하지 않습니다.

현재 알림 목록은 화면의 자원 필터와 독립적으로 scope 전체의 Pending, Firing, Error, NoData 상태를 표시합니다. 목록 제목에 전체 클러스터 또는 namespace 범위를 명시합니다. 빈 알림 목록만으로 정상 상태를 판단하지 말고 수집 상태와 자원 상태도 확인합니다.

## 중요 알림

기존 가용성·OOM·오류·노드 장애 알림에 다음 critical 규칙을 추가합니다.

| 조건 | 지속 시간 | 조치 |
|---|---|---|
| 노드 MemoryPressure 또는 PIDPressure | 1분 | 노드 상태와 프로세스·메모리 사용 확인, 워크로드 이동 |
| 쓰기 가능한 `/` 또는 `/local` 파일시스템 사용량 > 95% | 2분 | 공간 확보 또는 용량 증설 |
| PVC 사용량 > 95% | 2분 | 볼륨 확장 또는 데이터 정리 |

Grafana가 Prometheus를 조회하고 기존 Slack contact point로 보냅니다. critical은 그룹 대기 10초, 그룹 갱신 1분, 지속 장애 재알림 30분입니다. 평가 간격과 각 규칙의 지속 시간 이후 알림이 전송됩니다. webhook은 기존 Secret 환경변수로 전달합니다. 노드 전용 규칙은 EKS에만 제공됩니다.

변경은 GitOps 설정이며 실제 배포와 Slack 수신 확인은 별도입니다. 대시보드 JSON은 public GitHub main URL에서 Pod 시작 시 다운로드합니다. JSON 변경 후 values를 재생성하면 checksum이 변경되어 Grafana가 다시 시작하고 다운로드합니다. 다운로드 URL에도 checksum을 붙여 이전 GitHub raw 응답의 캐시를 피합니다. JSON 본문은 배포 values에 포함하지 않습니다.
