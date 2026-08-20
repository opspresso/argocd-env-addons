# CLAUDE.md

EKS 클러스터의 **addon** 을 Argo CD 로 배포하는 GitOps 저장소.

> 애플리케이션(서비스) 배포는 `argocd-env-demo` 저장소가 담당한다.
> 두 저장소는 디렉토리 모양이 닮았지만 **chart 규칙이 다르다** — 마지막 절 참고.

## 저장소 구조

```
addons.yaml            # App of Apps. Application `addons-demo` 가 addons/ 를 sync
addons/<addon>.yaml    # addon 별 ApplicationSet (배포 대상)
backup/<addon>.yaml    # 배포하지 않는 addon 의 ApplicationSet 보관소
charts/<addon>/        # wrapper Helm chart
env/<cluster>.yaml     # 클러스터별 변수. git files generator 입력이자 Jinja2 렌더 입력
install/               # Argo CD 최초 부트스트랩 (helm 직접 설치)
gen_chart.py           # addons/<addon>.yaml → charts/<addon>/Chart.yaml 초안 생성
gen_values.py          # 템플릿 × env/*.yaml → charts/<addon>/<env>/values-<cluster>.yaml
validate.py            # ApplicationSet 과 같은 조합으로 helm template 검증
build.sh               # 모든 chart 에 gen_values.py 실행. CI 에서 결과를 자동 커밋
update_env.sh          # AWS 조회 결과로 env/*.yaml 의 vpcId·acm_arn·target_group 갱신
update_versions.py     # versions.json 기준으로 upstream 최신 버전 조회, README 버전 테이블 갱신
versions.json          # update_versions.py 의 감시 목록. upstream chart 경로 + 버전 캐시
repos.txt              # update_versions.py 가 조회할 helm repo 목록 (helm repo add 입력)
```

`charts/` 의 모든 chart 는 `addons/` 나 `backup/` 에 ApplicationSet 을 가진다. 어느 쪽에도 없는
chart 는 배포 경로가 없다는 뜻이므로, 새로 만들 때는 ApplicationSet 을 함께 둔다.

`argo-cd` 의 Dex 설정에는 `argo-workflows-sso` OIDC 클라이언트가 남아 있다. argo-workflows 는
배포되지 않으므로 지금은 쓰이지 않는다.

## charts 규칙

```
charts/<addon>/
  Chart.yaml                    # wrapper chart. upstream chart 를 dependency 로 고정
  values.yaml                   # 모든 클러스터 공통 값
  values-template.yaml.j2       # Jinja2 템플릿 (렌더 소스)
  <env>/values-<cluster>.yaml   # build.sh 가 env/*.yaml 로 렌더한 결과
  README.md                     # (선택) 해당 addon 이 요구하는 SSM 파라미터 등록 절차
```

**이 저장소에는 `values-<phase>.yaml` 도 `versions-<phase>.json` 도 없다.** phase 개념은
`argocd-env-demo` 전용이다.

### 파일별 편집 규칙

| 파일 | 직접 수정 |
|---|---|
| `Chart.yaml` | O |
| `values.yaml` | O |
| `values-template.yaml.j2` | O |
| `<env>/values-<cluster>.yaml` | **X** — 언제나 생성물 |

**`<env>/values-<cluster>.yaml` 은 예외 없이 `values-template.yaml.j2` 의 렌더 결과다.**
클러스터별 값을 바꾸려면 템플릿을 고치고 `./build.sh` 를 돌린다. 렌더 결과를 직접 고치면
다음 build 에서 덮어써진다. `validate.py` 가 이 규칙을 검사하므로, 템플릿 없이 env 디렉토리만
있는 chart 는 CI 에서 실패한다.

클러스터별로 덮어쓸 값이 없는 chart 도 템플릿을 둔다 (`# no cluster-specific overrides` 한 줄).
ApplicationSet 의 `valueFiles` 에 적힌 파일이 없으면 Argo CD 가 sync 에 실패하기 때문이다.

### Chart.yaml

- `version` 은 upstream chart 버전과 같은 값을 쓴다 (예: argo-cd → `"10.2.2"`).
  순수 매니페스트만 담는 chart(`ingress-class`, `storage-class`)는 incubator `raw` chart 버전을 쓴다.
- dependency 이름이 디렉토리 이름과 다르면 `alias` 로 맞춘다
  (예: `kube-prometheus-stack` → `prometheus-stack`). 한 chart 를 두 번 쓰면 `alias` 로 구분한다
  (istio 의 `raw` / `tgb`).
- 버전 옆 `# helm chart <name> version` 주석을 유지한다.
- `gen_chart.py -r <addon>` 은 ApplicationSet 에서 Chart.yaml 초안을 만들어 주는 도구다.
  기존 chart 를 갱신할 때 돌리면 손으로 다듬은 내용(주석·alias·추가 dependency)이 날아간다.

### values 병합 순서

ApplicationSet 의 `helm.valueFiles` 순서 그대로다.

1. `values.yaml`
2. `<env>/values-<cluster>.yaml`

`external-dns` 처럼 클러스터별 값이 없는 addon 은 1번만 쓴다.

## env/<cluster>.yaml

- 파일 이름이 클러스터 이름이고, 안의 `cluster` 필드와 일치해야 한다 (`{{cluster}}` 로 치환됨).
- `env` 는 valueFiles 경로의 디렉토리(`{{env}}/values-{{cluster}}.yaml`)가 된다.
- `terraform-env-demo` 산출물(`vpcId`, `acm_arn`, `target_group.*`)은 손으로 넣지 말고
  `./update_env.sh` 로 갱신한다. 이미 값이 들어 있는 키만 교체하므로, 새 키는 먼저 추가해야 한다.
- `env` 를 바꾸면 렌더 출력 디렉토리도 함께 바뀐다. 옛 디렉토리에 남은 파일은 손으로 지운다.

## addons/<addon>.yaml

- `kind: ApplicationSet` + git files generator 로 `env/*.yaml` 을 읽어 클러스터별로 fan-out 한다.
- mgmt 클러스터 전용 addon 은 `env/eks-demo.yaml` 하나만 나열하고 `name` 에
  `# only management cluster` 주석을 단다.
- namespace 는 `addon-<name>`. upstream 관례가 강한 것만 예외(`istio-system`, `argocd`).
- label `opspresso.com/group: addons`, `opspresso.com/cluster: {{cluster}}` 를 유지한다.
- 배포를 멈출 때는 파일을 지우지 말고 `backup/` 으로 옮긴다. 되살릴 때는 반대로 옮긴다.
- `syncPolicy.automated` 는 대부분 켜져 있다. `argo-cd` 만 수동 sync 인데, Argo CD 가 자기 자신을
  올리는 앱이라 실패하면 되돌릴 수단까지 같이 사라지기 때문이다. 켜져 있는 addon 을 임의로 끄거나
  꺼져 있는 addon 을 임의로 켜지 않는다.

## 재생성 · 검증

```bash
./gen_values.py -r grafana   # 한 chart 렌더
./build.sh                   # 전체 chart 렌더
./validate.py                # helm template 로 전체 검증
./validate.py -r grafana     # 한 chart 만
```

`main` 에 push 하면 `.github/workflows/push.yml` 이 `build.sh` 를 돌려 렌더 결과를
`nalbam-bot` 이름으로 자동 커밋한다. 템플릿만 고쳐 push 해도 되지만, 로컬에서 렌더해
함께 커밋하면 diff 로 결과를 검토할 수 있다.

`.github/workflows/validate.yml` 이 PR 과 main push 에서 `build.sh` → `validate.py` 를 돌린다.
렌더한 뒤 검증하므로 PR 에 렌더 결과가 빠져 있어도 템플릿 변경분이 검사된다.
기본 대상은 `addons/` 뿐이다 — `backup/` 은 배포되지 않으므로 그쪽 upstream chart 가 사라져도
무관한 변경을 막지 않는다.

`validate.py` 는 `helm dependency update` 로 upstream chart 를 내려받는다.
결과물(`charts/*/charts/`, `charts/*/Chart.lock`)은 `.gitignore` 처리되어 있다.

## README 버전 테이블

`<!--- BEGIN_VERSION --->` ~ `<!--- END_VERSION --->` 구간은 이 저장소의 `update_versions.py` 가
`versions.json` 을 기준으로 생성한다. 직접 고치면 다음 실행에서 덮어써진다.
`update_versions.py` 는 `Chart.yaml` 을 절대 수정하지 않는 순수 감시 도구다 — 버전 업그레이드는
사람이 `Chart.yaml` 을 고치는 것으로 한다.

`.github/workflows/versions.yml` 이 매일 UTC 00 에 이 스크립트를 돌려 갱신분을 `nalbam-bot`
이름으로 main 에 커밋한다. 조회 실패가 있으면 run 은 실패로 표시되지만 성공한 chart 의
갱신분은 그대로 커밋된다.

- `CURRENT` — `charts/<NAME>/Chart.yaml` 의 version. 비어 있으면 그 chart 가 아직 없다는 뜻
- `LATEST` — upstream 저장소의 최신 버전 (괄호는 app version)
- ✅ 최신 / 빈칸 업그레이드 가능 / 🔒 잠금 / ⚪ 비활성

표의 행 목록은 `versions.json` 의 감시 목록이지 배포 목록이 아니다 — chart 디렉토리가 없는 항목
(`karpenter`)도 들어 있고, 배포 여부는 알 수 없다. 배포 여부는 `addons/` 에 ApplicationSet 이
있는지로 판단한다. 감시 목록의 key 가 chart 디렉토리 이름과 다르면 `path` 필드로 맞춘다
(`istiod` → `istio`).

`Chart.yaml` 버전을 올리면 다음 cron 에서 표에 반영된다. 즉시 맞추려면 수동으로 돌린다.
표와 `Chart.yaml` 이 다르면 `Chart.yaml` 이 기준이다.

```bash
cat repos.txt | xargs -I {} bash -c 'helm repo add {}'
helm repo update

./update_versions.py
```

`karpenter`(`public.ecr.aws` OCI) 조회는 `aws ecr-public get-login-password` 로
`helm registry login` 을 해 둬야 한다. 로그인이 없으면 해당 chart 만 Failed 로 집계되고
나머지는 정상 진행된다.

## argocd-env-demo 와 다른 점

같은 이름의 파일이 다른 의미를 가지므로 두 저장소를 오갈 때 주의한다.

| | argocd-env-addons (여기) | argocd-env-demo |
|---|---|---|
| 배포 단위 | addon | application |
| 템플릿 파일 | `values-template.yaml.j2` | 같음 |
| phase | 없음 | `values-<phase>.yaml`, `versions-<phase>.json` |
| `env/*.yaml` | `phase` 필드 없음 | `phase` 필드 있음 |
| valueFiles | `values.yaml` → `<env>/values-<cluster>.yaml` | 그 사이에 `values-<phase>.yaml` 이 들어감 |
| 렌더 출력 경로 | `charts/<addon>/<env>/` | 같음 |
| chart 버전 | upstream chart 버전을 그대로 | 자체 SemVer |
| 버전 배포 | 없음 (수동 chart 버전 변경) | `repository_dispatch` → `gitops.py`|

## 관련 저장소

- `terraform-env-demo` — EKS·VPC·ALB·IAM Role. `env/*.yaml` 에 들어가는 ARN 의 출처.
- `argocd-env-demo` — 애플리케이션 배포.
- `opspresso/helm-charts` — `gateway-api-crds` 등 자체 chart 의 저장소.
