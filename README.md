# argocd-env-addons

Argo CD로 클러스터 addon을 배포하는 GitOps 저장소다. 애플리케이션(서비스) 배포는
`argocd-env-apps` 저장소가 담당한다.

- Argo CD: <https://argo-cd.readthedocs.io/en/stable/getting_started/>
- ApplicationSet: <https://argocd-applicationset.readthedocs.io/en/stable/Getting-Started/>

## 운영 대상

| 플랫폼 | 상태 | 우선순위 | App of Apps | 설치 문서 |
| --- | --- | --- | --- | --- |
| EKS | 운영 중. `eks-demo`(Auto Mode, Kubernetes 1.37, phase `prod`) | 서비스 안정성 | `addons-eks.yaml` → `addons/eks/` | [install/eks](install/eks/README.md) |
| k3s | 배포하지 않음. 선언만 유지 | 리소스 사용량 | `addons-k3s.yaml` → `addons/k3s/` | [install/k3s](install/k3s/README.md) |

운영 클러스터 `eks-demo`의 Argo CD(`argocd.demo.rovr.dev`)가 `addons-eks.yaml`을 동기화한다.
addon 공개 주소는 `*.demo.rovr.dev`, 내부 주소는 `*.demo-in.rovr.dev`를 사용하며 ACM 인증서 `demo.rovr.dev`는
`terraform-env-demo`의 `3-alb`가 발급한다. `env/eks-demo-a.yaml`·`env/eks-demo-b.yaml`은 향후 서비스 클러스터
선언이다.
k3s 선언(`addons-k3s.yaml`, `addons/k3s/`, `env/k3s-demo.yaml`, `charts/*/k3s/`, `install/k3s/`)은 저장소에 남아 있지만
어느 클러스터에도 배포하지 않는다.
`local`은 공통 템플릿과 정책 검사에서만 지원하며, 로컬 클러스터용 env·Application·설치
스크립트는 제공하지 않는다.

## 저장소 구조

```text
addons-*.yaml     # 플랫폼별 App of Apps 설치 진입점
addons/<platform>/ # 배포 대상 Argo CD Application/ApplicationSet
backup/           # 배포하지 않는 addon 보관본
charts/<addon>/   # 공용 wrapper Helm chart와 플랫폼별 렌더 결과
env/              # 클러스터별 설정
config/           # Helm 저장소 목록과 chart 버전 감시 목록
scripts/          # 생성·검증·갱신 스크립트
install/          # 플랫폼별 Argo CD 최초 부트스트랩
docs/             # 운영 기준 문서
requirements/     # Python 실행(runtime.txt)·테스트(dev.txt) 의존성
tests/            # 자동화 테스트
```

배포 여부는 `addons/<platform>/`에 Application/ApplicationSet이 있는지로 판단한다.
`charts/`에만 있는 chart와 `backup/`의 addon은 배포되지 않는다.

## 설치

Argo CD 설치부터 addon 등록까지는 플랫폼별 설치 문서를 따른다.

- k3s(미배포 선언): `install/k3s/install.sh`가 Argo CD 설치 후 `addons`·`apps` AppProject를 만들고
  `addons-k3s.yaml`을 등록한다. [install/k3s](install/k3s/README.md)를 참고한다.
- EKS: [install/eks](install/eks/README.md)의 절차로 Argo CD를 설치한 뒤 App of Apps를 등록한다.

```bash
kubectl apply -n argocd -f https://raw.githubusercontent.com/opspresso/argocd-env-addons/main/addons-eks.yaml
```

App of Apps는 `addons/<platform>/` 아래 파일을 재귀로 동기화한다. 각 ApplicationSet은
git files generator로 `env/*.yaml`을 읽어 클러스터마다 Application을 만든다.

## 작업 절차

아래 명령은 저장소 루트에서 실행한다. 먼저 Python 의존성을 설치한다.

```bash
python3 -m pip install -r requirements/runtime.txt
```

### 클러스터별 값 변경

`charts/<addon>/<env>/values-<cluster>.yaml`은 **언제나** 생성물이다. 직접 고치면 다음 생성에서
덮어써진다.

1. `charts/<addon>/values-template.yaml.j2` 또는 `env/<cluster>.yaml`을 고친다.
2. 값을 다시 생성한다.

   ```bash
   ./scripts/build.sh                        # 전체 chart
   ./scripts/gen_values.py -p eks -r grafana # 한 chart, 한 플랫폼
   ```

3. [검증](#검증)을 실행하고 생성 결과와 함께 커밋한다.

`build.sh`는 파일만 생성하며 Git index·커밋·원격 저장소를 변경하지 않는다.

### addon 추가

1. `addons/<platform>/<addon>.yaml`에 ApplicationSet을 작성한다. [ApplicationSet 규칙](#applicationset-규칙)을 따른다.
2. `charts/<addon>/Chart.yaml` 초안을 만든다. 이 명령은 새 addon에만 쓴다.
   기존 chart에 실행하면 손으로 다듬은 주석·alias·추가 dependency가 사라진다.

   ```bash
   ./scripts/gen_chart.py -r <addon>
   ```

3. `values.yaml`과 `values-template.yaml.j2`를 작성한다. 클러스터별 값이 없어도 템플릿을 둔다.
4. `./scripts/build.sh`와 [검증](#검증)을 실행한다.
5. upstream chart가 있으면 `config/versions.json`에 감시 항목을 추가한다. 새 Helm 저장소는
   `config/repos.txt`에도 추가한다. [버전 관리](#버전-관리)를 참고한다.

### addon 배포 중지·재개

배포를 멈출 때는 `addons/<platform>/<addon>.yaml`을 지우지 말고 `backup/`으로 옮긴다.
되살릴 때는 반대로 옮긴다. `backup/`의 addon도 CI가 검증하므로 활성화할 때의 route·자원 계약이
유지된다. 단, 보관 chart의 자원 예산은 활성화 전에 실제 부하로 다시 확인한다.

### 인프라 재생성 후 env 갱신

`terraform-env-demo` 산출물(`vpcId`, `acm_arn`, `target_group.*`)은 손으로 넣지 않는다.
인프라를 재생성한 뒤 다음 명령으로 AWS를 조회해 값을 갱신하고, 변경분을 Git에 반영한 뒤
addon을 동기화한다.

```bash
./scripts/update_env.sh
./scripts/build.sh
```

- 이미 값이 들어 있는 키만 교체한다. 새 키는 먼저 `env/<cluster>.yaml`에 추가한다.
- AWS 리소스 이름에는 `aws_environment`(예: `demo`)를 사용한다. 배포 플랫폼인 `env`(예: `eks`)와 다르다.
- VPC나 Target Group 조회에 실패하면 중단한다.

## 구성 규칙

### `env/<cluster>.yaml`

`env/<cluster>.yaml`은 git files generator 입력이자 Jinja2 렌더 입력이다.

- 파일 이름은 클러스터 이름이며 `cluster` 필드와 같아야 한다. 다르면 생성에 실패한다.
- `env` 필드는 플랫폼(`eks`, `k3s`, `local`)이며 렌더 출력 디렉터리가 된다.
  `env`를 바꾸면 옛 디렉터리에 남은 파일은 손으로 지운다.
- 클러스터별 SSM 경로는 템플릿의 `{{cluster}}`로 만든다. 공통 `values.yaml`에 특정 클러스터의
  경로를 기본값으로 두지 않는다.

### ApplicationSet 규칙

- namespace는 `addon-<name>`이다. upstream 관례가 강한 것만 예외로 한다(`istio-system`, `argocd`).
- label `opspresso.com/group: addons`, `opspresso.com/cluster: {{cluster}}`를 유지한다.
- 관리 클러스터 전용 addon은 `env/eks-demo.yaml`만 나열하고 `name`에 `# only management cluster` 주석을 단다.
- `syncPolicy.automated`는 대부분 켜져 있다. EKS의 `argo-cd`만 수동 sync이고 k3s의 `argo-cd`는
  자동 sync다. 켜져 있는 자동 sync를 끄거나 꺼져 있는 것을 켜지 않는다.

### chart 구조

```text
charts/<addon>/
  Chart.yaml                   # wrapper chart. upstream chart를 dependency로 고정
  values.yaml                  # 모든 클러스터 공통 값
  values-template.yaml.j2      # 클러스터별 값의 Jinja2 템플릿
  eks/values-<cluster>.yaml    # EKS 렌더 결과
  k3s/values-<cluster>.yaml    # k3s 렌더 결과
  README.md                    # (선택) SSM 파라미터 등록 등 addon별 절차
```

- ApplicationSet은 `values.yaml` → `<env>/values-<cluster>.yaml` 순으로 병합한다.
- 덮어쓸 값이 없는 chart도 템플릿을 둔다(`# no cluster-specific overrides`). `valueFiles`에 적힌
  파일이 없으면 Argo CD sync가 실패한다.
- 이 저장소에는 `values-<phase>.yaml`이 없다. phase는 `argocd-env-apps` 전용 개념이다.
- `Chart.yaml`의 `version`은 upstream chart 버전과 같다. 매니페스트만 담는 chart
  (`ingress-class`, `storage-class`)는 `raw` chart 버전을 쓴다.

### 리소스 정의 순서

1. addon의 전용 chart와 values 옵션을 우선 사용한다. HTTPRoute, ServiceMonitor,
   PrometheusRule처럼 chart가 제공하는 리소스를 별도로 중복 정의하지 않는다.
2. 전용 옵션이 없는 리소스는 `https://charts.helm.sh/incubator`의 `raw` chart `0.2.5`를
   dependency로 추가하고 `raw.resources`에 선언한다. 일반 리소스를 addon의
   `extraObjects`·`extraManifests`에 넣지 않는다.
3. wrapper에 `templates/`를 만들지 않는다. 환경 분기는 `values-template.yaml.j2`에서 처리하고,
   Helm 평가가 꼭 필요하면 `raw.templates`를 사용한다. 공통·환경별 리소스 목록이 함께 필요하면
   raw alias로 분리한다. Helm의 values 목록은 병합되지 않고 뒤의 목록으로 교체되기 때문이다.

raw로 관리하는 예는 다음과 같다. 모두 전용 chart가 지원하지 않는 API다.

- k3s Traefik: k3s가 기본 설치한 chart를 소유하므로 별도 controller를 설치하지 않고 `HelmChartConfig`로 설정한다.
- EKS Auto Mode의 `TargetGroupBinding`
- Alloy의 `ApplicationNetworkPolicy`

addon chart가 렌더링하는 route·rule과 리소스 이름은 upstream 규칙을 따른다. URL·backend
Service·경보 그룹은 환경 설정에서 관리한다.

| addon | values 키 | 리소스 이름 |
| --- | --- | --- |
| Grafana·Atlantis | `route` | upstream 기본 |
| Argo CD·Rollouts | `httproute` | upstream 기본 |
| Argo Workflows | `httproute` | `argo-workflows-server` |
| Prometheus | `route` | `prometheus-prometheus` |
| Prometheus | `additionalPrometheusRulesMap` | `prometheus-agent-platform-workloads` (Agent 실행 경보) |

## 플랫폼별 리소스 규칙

### EKS

공통 `values.yaml`은 EKS 기본값이다. EKS는 기존 chart 기본값·env 설정·autoscaling 동작을 유지한다.
일반·init·테스트 컨테이너에는 양수 CPU/memory requests와 memory limit이 필요하다. CPU limit은
필수가 아니다. 구성별 예산과 확장 기준은 [Production addon 용량](docs/production-capacity.md)을 따른다.

### k3s·local

- env에 전역 `resources.enabled: false`, `autoscaling.enabled: false`를 선언하고 모든 chart가
  이 값을 따른다. Argo CD를 포함해 chart별로 같은 스위치를 두지 않는다.
- 컨테이너·초기화 컨테이너·Job·operator가 만드는 Pod에 CPU·메모리 requests/limits를 만들지 않는다.
  VictoriaMetrics의 `useDefaultResources`와 k3s Traefik의 `HelmChartConfig`도 같은 규칙을 적용해
  upstream 기본값이 리소스를 다시 넣지 않게 한다.
- HPA·VPA·KEDA autoscaler를 만들지 않는다.
- PVC의 storage 요청은 유지한다.

k3s 기본 CoreDNS·metrics-server는 k3s가 설치·업그레이드를 관리한다. `k3s-system-policy`는
Kubernetes 1.36 이상의 네이티브 `MutatingAdmissionPolicy`로 두 Deployment의 CPU·메모리
requests/limits만 제거하며, 별도 controller를 실행하지 않는다. 기존 설치에 처음 적용하면 두
Deployment를 갱신해야 새 Pod에 반영된다. `install/k3s/install.sh`는 정책 등록을 기다린 뒤 이 갱신과
준비 상태 확인을 수행한다.

`scripts/validate.py`는 실제 렌더 결과로 이 규칙을 검사한다. 새 chart와 upstream 갱신에도 같은
검사가 적용된다.

## 플랫폼별 운영 메모

### EKS 모니터링

- Grafana는 `https://grafana.demo.rovr.dev`에서 클러스터 안의 Prometheus와 Loki를 조회한다.
  경보 평가와 Slack 알림을 사용한다.
- Prometheus(`prometheus-stack`)는 클러스터·addon 메트릭과 앱 ServiceMonitor(`metrics.backend: prometheus`)를 수집한다.
- Alloy는 모든 노드의 Pod 로그를 Loki로 전송한다. Loki 내부 주소는 `loki.demo-in.rovr.dev`다.
- 저장소 크기와 보존 기간은 [Production addon 용량](docs/production-capacity.md)을 따른다.

### k3s 선언의 모니터링

배포하지 않는 k3s 선언은 Alloy가 앱·호스트 메트릭을 Grafana Cloud로 전송하고, Grafana 경보 평가·Slack 알림을
끄며, `local-path` 저장소를 사용한다. 세부 값은 `env/k3s-demo.yaml`과 각 chart의 `k3s/` 렌더 결과를 따른다.

### EKS Auto Mode NetworkPolicy

`addons/eks/eks-network-policy.yaml`은 `kube-system/amazon-vpc-cni` ConfigMap으로 관리형 Network
Policy Controller를 활성화한다. NodeClass의 `networkPolicy: DefaultAllow`만으로는 NetworkPolicy가
적용되지 않는다. [AWS 설정 계약](https://docs.aws.amazon.com/eks/latest/userguide/auto-net-pol.html)을
따르며, AWS가 controller와 node agent를 관리하므로 별도 CNI·DaemonSet을 설치하지 않는다.
k3s의 정책 처리는 k3s가 소유하므로 이 설정을 배포하지 않는다.

활성화하면 클러스터에 이미 선언된 모든 NetworkPolicy가 적용된다. 동기화 후 다음을 확인한다.

1. `kubectl get policyendpoints -A`로 정책 반영을 확인한다.
2. 다음 경로가 성공하는지 확인한다.
   - Forge controller의 전용 실행 namespace Pod 생성·exec
   - Sandbox → Forge 모델 Gateway
   - Argo CD 내부 통신
   - Studio → 서비스 API/MCP, 서비스 → Studio 정책 callback
3. Studio·Memory·Knowledge에 Sandbox 관리 권한이 없는지 확인한다.

## 검증

`scripts/validate.py`는 ApplicationSet과 같은 valueFiles 조합으로 `helm template`을 실행한다.
values 파일 누락이나 chart 오류를 Argo CD sync 전에 찾는다. upstream chart는
`helm dependency update`로 내려받으며 결과물(`charts/*/charts/`, `charts/*/Chart.lock`)은 Git에서 제외된다.

```bash
./scripts/validate.py                      # addons/ 전체
./scripts/validate.py -r grafana           # 한 chart
./scripts/validate.py -d addons -d backup  # 보관 addon 포함 (CI와 같음)
```

다음 경우 실패한다.

- 필수 템플릿 변수가 없거나 `env/<cluster>.yaml`의 파일 이름과 `cluster`가 다를 때
- 템플릿 없이 렌더 결과 디렉터리만 있는 chart가 있을 때
- 검증 디렉터리가 없거나 검사할 Application이 없을 때
- 렌더 결과가 [플랫폼별 리소스 규칙](#플랫폼별-리소스-규칙)을 어길 때

자동화 테스트에는 Helm, jq, yq v4, OpenSSL이 필요하다. AWS·Kubernetes 변경은 모의 명령으로 대체한다.
일부 테스트는 `validate.py`가 준비한 Helm 의존성을 사용하므로 검증 후에 실행한다.

```bash
python3 -m pip install -r requirements/dev.txt
python3 -m pytest -q
```

### CI

| workflow | 실행 시점 | 동작 |
| --- | --- | --- |
| `push.yml` (build) | `main` push | 값 생성 → `validate.py -d addons -d backup` → 테스트. 모두 성공하면 생성된 `charts/*/*/values-*.yaml`만 `nalbam-bot`이 커밋 |
| `validate.yml` | 수동 (`workflow_dispatch`) | 같은 검사를 읽기 권한으로 실행. 커밋하지 않음 |
| `versions.yml` | 매일 UTC 22:00, 수동 | upstream 최신 버전 조회 후 버전 표 갱신. [버전 관리](#버전-관리) 참고 |

Pull request는 CI를 시작하지 않는다. PR에 렌더 결과가 빠져 있어도 main push의 build가 렌더한 뒤
검증한다. 로컬에서 렌더해 함께 커밋하면 diff로 결과를 검토할 수 있다.

## 관련 문서

- [Production addon 용량](docs/production-capacity.md): EKS addon 자원 예산·확장 기준
- [Kubernetes monitoring](docs/kubernetes-monitoring.md): 클러스터·워크로드 대시보드와 중요 알림
- [Workspace와 Agent 서비스 관측성](docs/workspace-observability.md): Workspace·Agent 서비스 지표와 경보
- chart별 절차: [alloy](charts/alloy/README.md), [argo-cd](charts/argo-cd/README.md),
  [atlantis](charts/atlantis/README.md), [grafana](charts/grafana/README.md)

관련 저장소:

- `terraform-env-demo`: EKS·VPC·ALB·IAM Role. `env/*.yaml`에 들어가는 ARN의 출처
- `argocd-env-apps`: 애플리케이션 배포
- `opspresso/helm-charts`: `gateway-api-crds` 등 자체 chart

## 버전 관리

아래 표는 `scripts/update_versions.py`가 `config/versions.json`을 기준으로 생성한다. 직접 고치지 않는다.

- 표의 행은 감시 목록이며 배포 목록이 아니다. 배포 여부는 `addons/`로 판단한다.
- 감시 목록의 key가 chart 디렉터리 이름과 다르면 `path` 필드로 맞춘다(`istiod` → `istio`).
- `raw` chart만 쓰는 매니페스트 chart는 upstream 저장소가 보관(archived) 상태라 감시하지 않는다.
- 표와 `Chart.yaml`이 다르면 `Chart.yaml`이 기준이다.

| 열·표시 | 의미 |
| --- | --- |
| `CURRENT` | `charts/<NAME>/Chart.yaml`의 version. 비어 있으면 chart가 아직 없다 |
| `LATEST` | upstream 저장소의 최신 버전. 괄호는 app version |
| ✅ / 빈칸 / 🔒 / ⚪ | 최신 / 업그레이드 가능 / 잠금(`locked`) / 비활성(`disabled`) |

### 버전 조회

`versions.yml`이 매일 UTC 22:00(한국 시간 다음 날 07:00)에 조회하고, 갱신분을 `nalbam-bot`이 main에
커밋한다. 조회에 실패한 chart가 있으면 run은 실패로 표시되지만 성공한 chart의 갱신분은 커밋된다.
바로 갱신하려면 수동으로 실행한다.

```bash
cat config/repos.txt | xargs -I {} bash -c 'helm repo add {}'
helm repo update

./scripts/update_versions.py
```

로컬에 같은 이름의 Helm 저장소가 다른 URL로 등록되어 있으면 `helm repo add`가 갱신하지 않아 다른
결과가 나올 수 있다. `helm repo list`로 URL이 `config/repos.txt`와 같은지 확인한다.

감시 항목에 `"type": "oci"`를 지정하면 `helm show chart`로 OCI 레지스트리를 조회한다. 로그인이 필요한
레지스트리는 먼저 `helm registry login`을 실행한다. 로그인하지 못하면 해당 chart만 실패로 집계된다.

### 버전 업그레이드

`update_versions.py`는 `Chart.yaml`을 수정하지 않는다. 기록된 최신 버전을 `Chart.yaml`에 반영하려면
다음 스크립트를 실행한다. `jq`와 `yq` v4가 필요하다.

```bash
./scripts/update_charts.sh --dry-run          # 변경 대상만 출력
./scripts/update_charts.sh --chart istio      # 한 chart
./scripts/update_charts.sh                    # 전체
```

- `--chart`에는 감시 목록의 key, chart 디렉터리 이름, upstream chart 이름을 지정할 수 있다.
- 같은 upstream 저장소의 동일 버전 dependency를 함께 갱신한다.
- `locked`·`disabled` 항목과 로컬 chart가 없는 항목은 건너뛴다.
- 기록된 `current`와 `Chart.yaml`이 다르면 중단한다. 먼저 `update_versions.py`를 실행한다.
- 반영 후 [클러스터별 값 변경](#클러스터별-값-변경)과 같은 방법으로 값 생성·검증을 실행한다.
  표의 `CURRENT`는 다음 `update_versions.py` 실행 때 갱신된다.

<!--- BEGIN_VERSION --->
| NAME | | CURRENT | LATEST |
| --- | - | --- | --- |
| alloy |  | 1.14.3 | 1.14.4 (v1.21.3) |
| argo-cd | ✅ | 10.11.6 | 10.11.6 (v3.5.6) |
| argo-rollouts | ✅ | 2.43.8 | 2.43.8 (v1.10.1) |
| argo-workflows | ✅ | 2.0.14 | 2.0.14 (v4.1.6) |
| atlantis | ✅ | 6.16.2 | 6.16.2 (v0.48.2) |
| cert-manager | ✅ | v1.21.3 | v1.21.3 (v1.21.3) |
| external-dns | ✅ | 1.23.0 | 1.23.0 (0.23.0) |
| external-secrets | ✅ | 2.14.0 | 2.14.0 (v2.14.0) |
| gateway-api-crds |  | 1.6.1 | 1.6.3 (v1.6.3) |
| grafana | ✅ | 10.5.15 | 10.5.15 (12.3.1) |
| istio | ✅ | 1.31.3 | 1.31.3 (1.31.3) |
| kite | ✅ | 0.16.0 | 0.16.0 (v0.16.0) |
| loki | ✅ | 7.5.0 | 7.5.0 (3.6.16) |
| metrics-server | ✅ | 3.14.0 | 3.14.0 (0.9.0) |
| oauth2-proxy | ✅ | 10.7.1 | 10.7.1 (7.15.5) |
| prometheus-adapter | ✅ | 5.3.0 | 5.3.0 (v0.12.0) |
| prometheus-stack |  | 92.14.0 | 92.14.1 (v0.94.2) |
| victoria-metrics | ✅ | 0.97.0 | 0.97.0 (v1.155.0) |
| vllm-stack |  |  | 0.1.13 |
| workspace-metrics | ✅ | 8.7.1 | 8.7.1 (2.20.0) |
<!--- END_VERSION --->
