# grafana

## variables

```bash
# variables
export GITHUB_ORG="opspresso"

export ADMIN_USERNAME="admin"
export ADMIN_PASSWORD="REPLACE_ME"

export GRAFANA_GITHUB_ID="REPLACE_ME" # github OAuth Apps <https://github.com/organizations/opspresso/settings/applications>
export GRAFANA_GITHUB_SECRET="REPLACE_ME" # github OAuth Apps

export SLACK_WEBHOOK="REPLACE_ME" # slack incoming webhook bound to #noti-eks-demo

# put aws ssm parameter store
aws ssm put-parameter --name /k8s/common/admin-user --value "${ADMIN_USERNAME}" --type SecureString --overwrite | jq .
aws ssm put-parameter --name /k8s/common/admin-password --value "${ADMIN_PASSWORD}" --type SecureString --overwrite | jq .

# The alerting contact point reads this one.
aws ssm put-parameter --name /k8s/common/slack-webhook/grafana --value "${SLACK_WEBHOOK}" --type SecureString --overwrite | jq .

aws ssm put-parameter --name /k8s/${GITHUB_ORG}/grafana-github-id --value "${GRAFANA_GITHUB_ID}" --type SecureString --overwrite | jq .
aws ssm put-parameter --name /k8s/${GITHUB_ORG}/grafana-github-secret --value "${GRAFANA_GITHUB_SECRET}" --type SecureString --overwrite | jq .

# get aws ssm parameter store
export ADMIN_USERNAME=$(aws ssm get-parameter --name /k8s/common/admin-user --with-decryption | jq .Parameter.Value -r)
export ADMIN_PASSWORD=$(aws ssm get-parameter --name /k8s/common/admin-password --with-decryption | jq .Parameter.Value -r)

export SLACK_WEBHOOK=$(aws ssm get-parameter --name /k8s/common/slack-webhook/grafana --with-decryption | jq .Parameter.Value -r)

export GRAFANA_GITHUB_ID=$(aws ssm get-parameter --name "/k8s/${GITHUB_ORG}/grafana-github-id" --with-decryption | jq .Parameter.Value -r)
export GRAFANA_GITHUB_ID=$(aws ssm get-parameter --name "/k8s/${GITHUB_ORG}/grafana-github-secret" --with-decryption | jq .Parameter.Value -r)
```

## 클러스터 상태와 조기 경보

`kube-cluster`의 상단 **Host health**는 실제 호스트 메모리와 커널 메모리,
PSI(자원 대기 시간), swap, major page faults, 노드별 재시작과 probe 실패를 보여준다.
`Memory Requests / Allocatable`은 스케줄링 예약량이다. Pod working set과 함께 보더라도
커널의 BPF map 같은 호스트 할당량을 대신하지 못한다.

- `cluster`는 전체 화면에 적용한다. `Host instance`는 node-exporter 지표와 호스트 디스크에,
  `label_group`은 capacity 패널에, `namespace`는 workload 집계에 적용한다.
  핵심 수집 상태·노드별 재시작·probe 실패는 선택한 클러스터 전체를 보여준다.
- 시계열의 빈 구간을 연결하지 않는다. `up=0`은 수집 실패이고 빈 구간은 데이터 없음이다.
  수집 실패와 재시작은 최근 2~10분의 이력을 유지해 짧은 장애가 즉시 사라지지 않게 한다.
- 커널 메모리 누적은 6시간에서 수일 범위로 확인한다. `VmallocUsed` 증가 자체가 특정
  드라이버의 결함을 증명하지는 않는다. node-exporter의 `meminfo`와 `pressure` 지표를
  `/proc/vmallocinfo`, CNI 로그와 대조해 할당 주체를 확인한다.

EKS의 추가 Grafana 경보는 `config/node-health-alerts.yaml`에서 관리한다.
Prometheus의 Alertmanager는 비활성화되어 있으므로, 별도 PrometheusRule만 추가하면
Slack으로 전달되지 않는다. 이 규칙은 Grafana가 평가하고 기존 notification policy와
`slack` contact point를 사용한다. k3s/VictoriaMetrics에는 EKS 전용 job 이름의 규칙을
프로비저닝하지 않는다.

| 조건 | 유지 시간 | 의미 |
| --- | --- | --- |
| 호스트 실제 메모리 사용률 >85% / >92% | 5분 / 2분 | 노드별 메모리 여유 감소 |
| Vmalloc / 물리 메모리 >20% | 15분 | 커널 할당이 차지하는 비중 증가 |
| Vmalloc이 최근 6시간에 256MiB 초과 증가 | 15분 | 지속적인 커널 할당 누적 후보 |
| 메모리 PSI >10% | 2분 | 메모리 대기가 서비스 응답을 지연 |
| 핵심 target에서 최근 2분 내 scrape 실패 | 즉시 | 짧은 노드 정지와 수집 공백 |
| 필수 scrape job이 discovery에서 사라짐 | 2분 | 수집 대상 자체가 없는 상태 |
| 한 노드에서 10분 내 restart 증가량 >2 | 즉시 | 종료 reason과 무관한 동시 장애 |
| 한 kubelet에서 5분 내 liveness 실패 증가량 >2 | 즉시 | 재시작 이전의 응답 불능 |

임계값은 운영 초기값이다. 정상 노드의 장기 기준선과 비교하여 조정한다. `increase`는 구간 경계 값을
추정하므로 정수가 아닐 수 있다. 커널 증가 경보는 6시간 전 값과 직접 비교하며 새 노드의
짧은 관측 구간을 6시간으로 외삽하지 않는다. 핵심 호스트 지표 전체가 사라지면 NoData,
쿼리 실행 오류는 Alerting으로 처리한다. PSI 미지원, 6시간 전 이력이 없는 새 노드의
커널 증가 경보와 정상 상태에서 결과가 비는 `absent` 경보는 예외이며, 별도의 scrape 상태·job 누락 경보로 수집 자체를 감시한다.

node-exporter와 kubelet probes는 15초마다 수집한다. 기존에 수집한 과거 데이터에는
새 node-exporter `node` 라벨이 없으므로, 호스트 패널은 `instance`로 과거와 현재를 비교한다.

### 반영과 검증

JSON URL은 Grafana의 init container가 Pod 시작 시 내려받는다. `scripts/build.sh`는
저장소의 대시보드 JSON 해시를 Pod annotation에 기록하므로 JSON만 바꿔도 GitOps 동기화 시
Grafana가 다시 시작되어 내용을 읽는다. `Recreate` 전략으로 이때 Grafana가 잠시 중단된다.
JSON과 생성 values를 같은 변경에 포함하고, 동기화 후 실제 dashboard와 provisioned rules를
확인한다. UI에서 provisioned dashboard를 수정해도 다음 프로비저닝으로 덮어써질 수 있다.

```bash
./scripts/build.sh
./scripts/validate.py -r grafana
./scripts/validate.py -r prometheus-stack
python3 -m pytest -q tests/test_node_observability.py
```

경보 테스트는 Helm이 렌더한 Grafana query·threshold·유지 시간으로 Prometheus 규칙을 구성해
실제 `promtool`로 건강한 노드, 메모리 누적, 짧은 scrape 실패, discovery 누락, 동시 재시작을
평가한다. 로컬 `promtool` 또는 이미 내려받은
`quay.io/prometheus/prometheus:v3.14.0-distroless` 이미지를 사용하며 임의로 설치하지 않는다.

Grafana 자체가 멈추면 Grafana 경보도 평가·전송할 수 없다. 독립된 외부 감시에서
Grafana·Prometheus 도달성과 알림 heartbeat를 확인해야 전체 알림 경로까지 보장할 수 있다.
코드·PromQL 검증은 Slack 전달 성공을 대신하지 않는다.

## 두 대시보드의 역할

`kube-cluster`는 노드와 모니터링 기반 시설을 다룬다. 상단의 현재 위험 지표와 노드별 표에서
문제 노드를 찾고, 아래에서 메모리·커널·PSI·swap·수집 상태·노드별 재시작을 확인한다.
스케줄링 예약량은 별도 영역에 두며, 물리 NIC의 네트워크와 쓰기 가능한 root/data 디스크를
집계한다. 변경 가능한 exporter 라벨은 시계열에서 제거해 배포 전후 동일 instance가
서로 다른 선으로 표시되지 않게 한다. NotReady/Unknown이 1분 유지되면 critical,
노드 CPU 사용률이 90%를 10분 초과하면 warning 알림을 보낸다.

`kube-workload`는 namespace·종류·workload로 선택한 애플리케이션을 다룬다.
Deployment·StatefulSet·DaemonSet의 복제본은 해당 종류의 메타데이터로 계산하므로,
Pod가 하나도 없어도 전체 중단을 감지하며 같은 이름의 다른 종류로 대체하지 않는다.
Pod·컨테이너 조인은 cluster와 namespace를 포함한다. CronJob·Job에는 복제본 목표 대신
Pod phase와 실패 사유를 사용하며 replica 패널은 `No replica metrics`로 표시한다.

상단은 수집 상태, 부족한 복제본, NotReady Pod, 최근 재시작·OOM, 서비스 오류와
최악 컨테이너의 memory/limit을 보여준다. 아래에는 현재 Pod 문제, 복제본 추이,
종료 사유와 시간, sidecar를 포함한 컨테이너별 자원, 서비스·PVC·로그가 이어진다.
요청량은 실사용량과 구별하며, limit이 없거나 HTTP 트래픽이 없으면 정상 0%로 표시하지 않는다.
로그 Pod 목록도 이름 접두사 대신 owner recording rule에서 구한다.

서비스 패널은 Istio의 destination workload·namespace·service를 사용한다. HTTP 5xx와
transport code `0`을 실패로 계산한다. 메시에 관측되지 않는 요청은 표시할 수 없으며,
HTTP 수치가 없어도 replica·Pod 상태는 별도로 확인해야 한다. kube-state-metrics 수집 실패 시
상단 수집 상태와 클러스터 경보를 먼저 확인한다.

워크로드 경보는 `config/workload-health-alerts.yaml`이 단일 원천이다. 기존 workload 규칙도
같은 파일에서 관리하며 UID를 유지해 파일 간 중복 선언을 피한다. 기존 Slack 정책을 사용한다.

| 이슈 | 경보 조건 |
| --- | --- |
| 전체 복제본 중단 | desired >0이고 available=0인 상태 1분, critical |
| 일부 복제본 부족 | available >0인 부분 가용 상태에서 부족이 3분 지속, warning |
| OOM | 최근 10분 restart 증가와 마지막 OOMKilled 사유 확인 즉시, critical |
| 이미지·설정·runtime 오류 | container waiting reason이 2분 유지, critical |
| CrashLoopBackOff | 2분 유지, warning |
| 컨테이너 메모리 여유 부족 | 양수 limit 대비 working set >90%가 5분 유지, warning |
| HTTP·transport 오류 | 0.1 req/s 초과 트래픽에서 오류율 >5%가 2분 유지, critical |

경보 링크는 해당 대시보드·패널을 가리킨다. owner가 확인되는 경보에는 namespace·종류·workload를
선택한 `dashboard_url`도 포함한다. 이 링크의 Grafana label template은 Helm `tpl`을 통과하도록
명시적으로 escape한다. 신규 규칙 검사는 전체 중단·scale-to-zero·다른 종류/클러스터의 같은 이름,
100% HTTP 실패·트래픽 없음·limit 없음·OOM을 실제 PromQL 평가기로 구분한다.
