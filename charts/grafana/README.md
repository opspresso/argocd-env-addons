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

## 대시보드

Grafana 홈은 **Cluster Overview**다. 문제를 찾을 때는 아래 표의 위쪽 대시보드에서 아래쪽 대시보드로 내려간다.

| 대시보드 (uid) | 질문 | 주요 내용 |
| --- | --- | --- |
| Cluster Overview (`cluster-overview`) | 지금 무엇이 잘못됐고 여유는 얼마나 남았나 | 상태 타일, 문제 목록, 노드 표, ingress 서비스 표, 추이 |
| Service Status (`service-status`) | 배포된 서비스가 각각 정상인가 | namespace별 workload 표, ingress 트래픽·오류·지연, 자원, 오류 로그 |
| Kubernetes Cluster (`kube-cluster`) | 어느 노드가 왜 불안정한가 | 호스트 메모리·커널 vmalloc·PSI·swap, 수집 상태, 노드별 재시작 |
| Kubernetes Workload (`kube-workload`) | 이 workload의 어느 Pod·컨테이너가 문제인가 | 복제본, 종료 사유, 컨테이너 자원, 서비스 트래픽, PVC, 로그 |
| Workspace Capacity (`workspace-capacity`) | Agent workspace 용량이 남아 있나 | workspace quota, sandbox 자원, Forge·Knowledge 가용성 |
| ArgoCD, Istio Mesh, Istio Control Plane | upstream 제공 대시보드 | Argo CD 동기화, mesh 요약, istiod |

### Cluster Overview

- 첫 줄의 문제 타일(firing 경보, NotReady 노드, degraded workload, 준비되지 않은 Pod, 재시작, OOM, 비정상 Argo CD 앱)은
  정상일 때 0이고 초록색이다. `Ready nodes`와 `Nodes launched (24h)`는 정보용 파란색이다.
- 둘째 줄은 ingress 요청량·오류율·p95 지연과 용량을 보여준다. `CPU requested`·`Memory requested`는 Pending·Running Pod의
  requests만 합한다. EKS Auto Mode는 스케줄할 수 없는 Pod가 생기면 노드를 추가하므로 높은 예약률 자체는 문제가 아니다.
  스케줄할 수 없는 Pod가 문제 신호다.
- 문제 표(경보, degraded workload, 준비되지 않은 Pod, Argo CD 앱)는 문제가 없으면 빈 상태 문구를 보여준다.
  workload를 누르면 `kube-workload`, namespace를 누르면 `service-status`가 열린다.

### Service Status

- `Namespace` 변수는 여러 개를 고를 수 있고 기본값은 전체다.
- Workloads 표는 Deployment·StatefulSet·DaemonSet마다 한 행이다. `Availability`는 available/desired이고
  `CPU / request`는 사용량/requests 합계다. `Worst memory / limit`은 workload에서 limit 대비 사용률이 가장 높은 컨테이너다.
  limit이 없으면 N/A다. 가용성이 낮은 행이 위로 정렬된다.
- 트래픽 패널은 Istio ingress gateway가 보고한 값(`reporter="source"`)이다. 이 클러스터에서는 sidecar의 destination 보고가
  거의 없어서 upstream Istio Service·Workload 대시보드는 비어 있었다. 그래서 두 대시보드를 제거하고 이 화면으로 대체했다.
- 오류 로그는 Loki에서 `level=error|fatal|critical`, `ERROR`, `FATAL`, `CRITICAL`, `panic:`, `Exception`과 일치하는 줄이다.

### 공통 규칙

- 실패 요청은 5xx와 transport code `0`이다. 클라이언트가 먼저 연결을 끊은 요청(response flag `DC`)은 서버 실패가 아니므로 제외한다.
  대시보드와 경보가 같은 정의를 쓴다.
- 대시보드 임계값은 경보 임계값과 같다. 빨간 패널과 Slack 경보는 같은 상태를 뜻한다.
- 시계열의 빈 구간을 연결하지 않는다. `up=0`은 수집 실패이고 빈 구간은 데이터 없음이다.
- `kube-cluster`의 호스트 패널은 `instance`로 과거와 현재를 비교한다. 과거 node-exporter 지표에는 `node` 라벨이 없다.

## 경보

Prometheus의 Alertmanager는 비활성화되어 있다. Grafana가 `config/*.yaml`의 규칙을 평가하고 `slack` contact point로
`#noti-eks-demo`에 보낸다. k3s에는 경보를 프로비저닝하지 않는다. Argo CD 앱의 degraded·sync 실패는
Argo CD notifications가 보내므로 Grafana 규칙으로 중복하지 않는다.

### 심각도와 알림 정책

| severity | 의미 | 반복 |
| --- | --- | --- |
| `critical` | 서비스 중단이나 데이터 손실이 진행 중이다. 바로 대응한다. | 1시간 |
| `warning` | 당일 안에 확인한다. 용량 감소·불안정 징후다. | 12시간 |

경보는 `grafana_folder, alertname, cluster, namespace`로 묶는다. Slack 메시지는 `templates.yaml`의 `addons.slack.*` 템플릿으로
만든다. 제목은 상태·경보 이름·namespace다. 본문은 경보마다 summary(대상과 측정값), description(영향과 첫 조치),
대시보드·규칙·silence 링크다. resolved 메시지는 summary만 남긴다. 한 메시지에는 최대 10개 경보를 표시한다.

### 오류와 데이터 없음 처리

- Prometheus 쿼리가 실패하면 모든 규칙은 직전 상태를 유지한다(`execErrState: KeepLast`). 이전에는 오류 상태가
  모든 규칙을 Alerting으로 바꿔서, Prometheus가 재시작할 때 NotReady·PVC 95%·메모리 92% 경보가 동시에 거짓으로 발생했다.
- 쿼리 실패는 `Prometheus is not answering alert queries` 규칙 하나만 알린다. 이 규칙은 `vector(0)`을 평가하고
  쿼리가 3분 동안 실패하면 critical을 보낸다.
- 결과가 비면 정상이다(`noDataState: OK`). 수집 대상 자체가 사라지면 `Core monitoring job has no targets`가 알린다.
- Grafana 자체가 멈추면 Grafana 경보도 평가·전송할 수 없다. 외부 감시로 Grafana 도달성과 알림 heartbeat를 확인해야
  알림 경로 전체를 보장할 수 있다.

### 노드·수집 (`config/node-health-alerts.yaml`)

| 경보 | 조건 | 유지 | severity |
| --- | --- | --- | --- |
| Prometheus is not answering alert queries | Prometheus 쿼리 실패 | 3분 | critical |
| Kubernetes node is not Ready | Ready가 false/unknown. Auto Mode가 drain 중인 노드(`karpenter.sh/disrupted`)는 제외 | 2분 | critical |
| Node under memory or PID pressure | kubelet MemoryPressure/PIDPressure | 1분 | critical |
| Node under disk pressure | kubelet DiskPressure | 5분 | critical |
| Node filesystem above 85% / 95% used | 쓰기 가능한 `/`, `/local` | 10분 / 2분 | warning / critical |
| Host memory usage above 85% / 92% | 1 - MemAvailable/MemTotal | 5분 / 2분 | warning / critical |
| Kernel vmalloc above 20% of RAM | VmallocUsed / MemTotal | 15분 | warning |
| Kernel vmalloc growing over 6 hours | 6시간 전보다 256MiB 초과 증가 | 15분 | warning |
| Tasks stalled on memory above 10% | 메모리 PSI | 2분 | warning |
| Node CPU busy above 90% | 비유휴 CPU | 10분 | warning |
| Core monitoring target down | node-exporter·kubelet·apiserver·kube-state-metrics·Loki target의 `up=0` | 5분 | warning |
| Core monitoring job has no targets | 위 job이 discovery에서 사라짐 | 2분 | critical |
| Several containers restarting on one node | 한 노드에서 10분 안에 서로 다른 컨테이너 3개 이상 재시작 | 즉시 | warning |
| Liveness probes failing for several pods on one node | 한 kubelet에서 5분 안에 Pod 2개 이상 liveness 실패 | 즉시 | warning |

Auto Mode는 하루 10대 안팎의 노드를 교체한다. 교체되는 노드의 target은 몇 분 동안 실패한 뒤 discovery에서 사라진다.
`Core monitoring target down`이 5분을 기다리는 이유다. 한 컨테이너의 반복 재시작은 노드 경보가 아니라
workload 경보(`Container restarting repeatedly`)로 보고한다.

### Workload (`config/workload-health-alerts.yaml`)

| 경보 | 조건 | 유지 | severity |
| --- | --- | --- | --- |
| Workload has no available replicas | desired >0이고 available=0 | 3분 | critical |
| Workload replicas below desired | 일부만 available | 10분 | warning |
| Service HTTP error rate above 5% | ingress 요청 >0.1 req/s 중 5xx·code 0(`DC` 제외) >5% | 5분 | critical |
| Container restarting repeatedly | 한 컨테이너가 15분 안에 3회 이상 재시작(init·sidecar 포함) | 즉시 | warning |
| Workload container OOMKilled | 최근 10분 재시작의 마지막 종료 사유가 OOMKilled | 즉시 | warning |
| Workload container cannot start | ImagePullBackOff·CreateContainerConfigError 등 | 5분 | warning |
| Workload container memory above 90% of limit | 양수 memory limit 대비 working set | 5분 | warning |
| Pod failed recently | 최근 1시간 안에 Failed가 된 Pod. Job·Workflow Pod, 노드 종료로 멈춘 Pod 제외 | 5분 | warning |
| Job failed | 최근 1시간 안에 실패한 Job | 즉시 | warning |
| Pod unschedulable | 스케줄할 수 없는 Pod | 10분 | warning |
| PersistentVolume above 85% / 95% used | kubelet volume 통계 | 15분 / 2분 | warning / critical |

- Recreate 전략의 단일 replica workload(Grafana, Prometheus, Loki)는 배포할 때마다 잠시 중단된다. 전체 중단 경보는
  이 정상 재시작을 넘는 3분을 기다린다.
- `Pod failed recently`와 `Job failed`는 실패 후 1시간이 지나면 해소된다. 실패한 객체가 남아 있어도 12시간마다
  같은 경보를 반복하지 않게 하기 위해서다.
- `CPU/Memory requests above 90%` 경보는 제거했다. Auto Mode에서는 높은 예약률이 정상 운영 상태이고,
  실제 문제는 `Pod unschedulable`로 알린다. `Istio success rate below 99%`는 HTTP 오류율 경보와 같은 신호여서 합쳤다.
  `Container restarted after Error`는 반복 재시작 경보로 대체했다. 제거한 규칙은 `deleteRules`로 Grafana에서 삭제한다.

### 기타 규칙

- `config/cni-health-alerts.yaml`: Alloy가 수집한 Loki 로그에서 AWS network policy agent의 egress BPF attach 실패를 즉시 알린다(critical).
- `config/workspace-notifications.yaml`: `config/workspace-alerts.yaml`의 Prometheus 규칙(Forge·Knowledge·Studio)이 firing이면
  해당 규칙의 severity로 전달한다.

### 규칙 작성 규칙

- chart는 alerting 항목을 Helm `tpl`로 렌더한다. Grafana 템플릿 문법은 raw string으로 감싼다.
  예: ``summary: 'Node {{`{{ $labels.node }}`}} is NotReady'``
- 모든 규칙에 `severity`, summary(대상과 값), description(영향과 첫 조치), `__dashboardUid__`·`__panelId__`를 둔다.
  owner가 있는 workload 경보는 변수가 채워진 `dashboard_url`도 둔다.
- UID를 바꾸거나 규칙을 지우면 `deleteRules`에 옛 UID를 추가한다. Grafana 파일 프로비저닝은 파일에서 사라진 규칙을 지우지 않는다.

## 반영과 검증

대시보드는 두 경로로 프로비저닝한다. 두 경로 모두 코드에서 만들어지므로 Grafana를 재설치해도 같은 대시보드가 생긴다.

| provider | 원본 | 전달 방식 |
|---|---|---|
| `managed` | 이 저장소의 `charts/grafana/dashboards/*.json` | `templates/dashboards.yaml`이 ConfigMap `grafana-dashboards`로 묶고 `/var/lib/grafana/dashboards/managed`에 mount한다 |
| `upstream` | 게시자 원본의 최신 버전: Argo CD `examples/dashboard.json`(master), grafana.com Istio 7639·7645(`revision: latest`) | Pod 시작 시 init container가 영구 볼륨의 `/var/lib/grafana/dashboards/upstream`에 내려받는다 |

- `managed` 대시보드를 바꾸면 ConfigMap이 갱신되고 Grafana가 mount된 파일 변경을 읽는다. Pod를 재시작하지 않는다.
  JSON 파일을 지우면 Grafana에서도 사라진다.
- ConfigMap이 256 KiB를 넘으므로 이 ConfigMap만 `argocd.argoproj.io/sync-options: ServerSideApply=true`로 동기화한다.
  앱 전체에 server-side apply를 켜면 bound PVC의 immutable spec 변경으로 동기화가 실패한다.
- `upstream` 대시보드는 Pod가 시작될 때마다 최신 버전을 받는다. 목록에서 지운 대시보드의 파일은 영구 볼륨에 남으므로,
  Grafana에서 지우려면 provider 이름을 바꾼다.
- UI에서 provisioned dashboard를 수정해도 다음 프로비저닝에서 덮어써진다.

```bash
./scripts/build.sh
./scripts/validate.py -r grafana
python3 -m pytest -q tests/test_node_observability.py tests/test_workload_dashboard.py tests/test_cni_observability.py
```

경보 테스트는 Helm이 렌더한 query·threshold·유지 시간으로 Prometheus 규칙을 만들고 `promtool`로 평가한다.
노드 교체, 짧은 스케줄 대기, 클라이언트 연결 끊김, 단일 컨테이너 재시작처럼 알리지 않아야 할 경우도 검사한다.
로컬 `promtool` 또는 이미 내려받은 `quay.io/prometheus/prometheus:v3.14.0-distroless` 이미지를 사용하며
없으면 테스트를 건너뛴다. 코드·PromQL 검증은 Slack 전달 성공을 대신하지 않는다.
