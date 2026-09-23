# argocd-env-addons

* <https://argo-cd.readthedocs.io/en/stable/getting_started/>
* <https://argocd-applicationset.readthedocs.io/en/stable/Getting-Started/>

## 저장소 구조

```text
addons-*.yaml     # App of Apps 설치 진입점
addons/           # 플랫폼별 Argo CD Application/ApplicationSet
backup/           # 배포하지 않는 addon 보관본
charts/           # 공용 wrapper Helm chart와 렌더 결과
env/              # 클러스터별 설정
scripts/          # 빌드·생성·갱신·검증 스크립트
config/           # Helm 저장소 목록과 chart 버전 감시 목록
requirements/     # Python 실행(runtime.txt)·테스트(dev.txt) 의존성
install/          # 플랫폼별 Argo CD 최초 부트스트랩
tests/            # 자동화 테스트
```

아래 명령은 저장소 루트 기준이다. 스크립트는 다른 디렉터리에서도 경로를 지정해 실행할 수 있다.
Python 의존성은 `python3 -m pip install -r requirements/runtime.txt`로 설치한다.

## see argocd

* See <https://github.com/opspresso/argocd-env-addons/tree/main/install/eks/>
* k3s 설치는 <https://github.com/opspresso/argocd-env-addons/tree/main/install/k3s/> 참고

현재 배포·설치 대상은 EKS와 k3s다. `local`은 공통 템플릿과 정책 검사에서만 지원하며,
로컬 클러스터용 env·Application·설치 스크립트는 제공하지 않는다.

## addons

> addons 를 등록 합니다.

```bash
kubectl apply -n argocd -f https://raw.githubusercontent.com/opspresso/argocd-env-addons/main/addons-eks.yaml
```

`addons/eks/<addon>.yaml` 과 `addons/k3s/<addon>.yaml` 이 배포 대상이고,
`backup/<addon>.yaml` 은 배포하지 않는 보관본이다.
배포를 멈출 때는 파일을 지우지 말고 `backup/` 으로 옮긴다.

## charts

```
charts/<addon>/
  Chart.yaml                   # wrapper chart. upstream chart 를 dependency 로 고정
  values.yaml                  # 공통 값
  values-template.yaml.j2      # jinja2 템플릿
  eks/values-<cluster>.yaml    # EKS 렌더 결과
  k3s/values-<cluster>.yaml    # k3s 렌더 결과
```

`<env>/values-<cluster>.yaml` 은 **언제나** `values-template.yaml.j2` 의 렌더 결과다.
직접 고치지 말고 템플릿을 고친 뒤 `./scripts/build.sh` 를 돌린다.
덮어쓸 값이 없는 chart 도 템플릿을 둔다 — ApplicationSet 의 `valueFiles` 에 적힌 파일이 없으면
sync 에 실패하기 때문이다.

ApplicationSet 은 `values.yaml` → `<env>/values-<cluster>.yaml` 순으로 병합한다.
이 저장소에는 `values-<phase>.yaml` 이 없다 — phase 는 `argocd-env-demo` 전용 개념이다.

## env

### EKS Auto Mode NetworkPolicy

`addons/eks/eks-network-policy.yaml`은 `kube-system/amazon-vpc-cni` ConfigMap으로
관리형 Network Policy Controller를 활성화한다. NodeClass의 `networkPolicy: DefaultAllow`만으로는
NetworkPolicy가 적용되지 않는다. [AWS 설정 계약](https://docs.aws.amazon.com/eks/latest/userguide/auto-net-pol.html)을 따른다.
AWS가 controller와 node agent를 관리하므로 별도 CNI·DaemonSet을 설치하지 않는다.

활성화하면 클러스터에 이미 선언된 모든 NetworkPolicy가 적용 대상이 된다. 동기화 후
`kubectl get policyendpoints -A`와 실제 허용·차단 경로를 확인한다. Agent Studio Pod에서
Workspace Docker API의 `/_ping`은 성공해야 하고, Agent Memory 같은 다른 namespace에서는
같은 호출이 차단돼야 한다. Argo CD 내부 통신과 Studio → MCP 경로도 확인한다.
k3s의 정책 처리는 k3s가 소유하며 이 EKS 설정을 배포하지 않는다.

### 클러스터 입력

`env/<cluster>.yaml` 은 git files generator 입력이자 jinja2 렌더 입력이다.
파일 이름은 클러스터 이름이고 `cluster` 필드와 일치해야 한다. `env` 필드는 `eks`, `k3s`, `local`이며
valueFiles의 디렉토리가 된다.

`terraform-env-demo` 산출물(`vpcId`, `acm_arn`, `target_group.*`)은 AWS 를 조회해 갱신한다.
이미 값이 들어 있는 키만 교체한다. AWS 리소스 이름에는 `aws_environment`(예: `demo`)를
사용하며, 배포 플랫폼인 `env`(예: `eks`)와 구분한다. VPC나 Target Group 조회에
실패하면 중단한다. 인프라를 재생성한 뒤에는 다음 두 명령으로 ARN과 배포 값을
갱신하고 변경분을 Git에 반영한 뒤 addons를 동기화한다.

```bash
./scripts/update_env.sh
./scripts/build.sh
```

## 리소스·autoscaling 규칙

공통 `values.yaml`은 EKS를 기본으로 한다. EKS는 기존 chart 기본값과 env 설정을 사용한다.
`k3s`·`local`는 `resources.enabled: false`, `autoscaling.enabled: false`로 선언하고,
모든 chart가 이 두 전역 값을 따른다. Argo CD도 별도 resource/autoscaling 스위치를 두지 않는다.

k3s·local에서는 CPU·메모리 requests/limits와 HPA·VPA·KEDA autoscaler를 생성하지 않는다.
PVC의 storage 요청은 유지한다. VictoriaMetrics의 `useDefaultResources`와 k3s Traefik의
`HelmChartConfig`도 같은 규칙을 적용해 operator·upstream 기본값이 리소스를 다시 주입하지 않게 한다.
`scripts/validate.py`는 실제 렌더 결과의 컨테이너·초기화 컨테이너·Job·operator CR까지 검사한다.

## gen chart

`addons/<platform>/<addon>.yaml` 에서 `charts/<addon>/Chart.yaml` 초안을 만든다.
기존 chart 에 돌리면 손으로 다듬은 주석·alias·추가 dependency 가 사라지므로 새 addon 을 만들 때만 쓴다.

```bash
./scripts/gen_chart.py -r grafana
```

## gen values

`values-template.yaml.j2` 를 `env/*.yaml` 마다 렌더해 `charts/<addon>/<env>/` 에 저장한다.
`./scripts/build.sh` 는 모든 chart 에 대해 이것을 실행한다.
이 스크립트는 파일만 생성하며 Git index·커밋·원격 저장소를 변경하지 않는다.

```bash
./scripts/build.sh

./scripts/gen_values.py -p eks -r grafana
```

## validate

ApplicationSet 이 지정한 것과 같은 valueFiles 조합으로 `helm template` 을 돌린다.
values 파일 누락이나 chart 오류를 Argo CD sync 가 아니라 CI 에서 잡기 위한 것이다.

```bash
./scripts/validate.py

./scripts/validate.py -r grafana
./scripts/validate.py -d addons -d backup   # 미배포 addon 까지
```

필수 템플릿 변수가 없거나 `env/<cluster>.yaml`의 파일명과 `cluster`가 다르면 생성에 실패한다.
검증 디렉터리가 없거나 검사할 Application이 하나도 없을 때도 실패로 처리한다.

자동화 테스트는 다음 명령으로 실행한다. 테스트에는 Helm, jq, yq v4, OpenSSL이 필요하며
AWS·Kubernetes 변경은 모의 명령으로 대체한다.

```bash
python3 -m pip install -r requirements/dev.txt
python3 -m pytest -q
```

PR과 main push에서 테스트 → 값 생성 → Helm 검증을 실행한다. main workflow는 모든 검사가
성공한 뒤 생성된 `charts/*/*/values-*.yaml`만 커밋·푸시한다.

## versions

아래 표는 `scripts/update_versions.py` 가 `config/versions.json` 을 기준으로 생성한다. 여기서 직접 고치지 않는다.
`versions` workflow 가 매일 UTC 22:00(한국 시간 다음 날 07:00)에 실행해 갱신분을 main 에 커밋하므로, `Chart.yaml` 버전을
올리면 늦어도 다음 날 표에 반영된다.

* `CURRENT` — `charts/<NAME>/Chart.yaml` 의 version. 비어 있으면 그 chart 가 아직 없다는 뜻
* `LATEST` — upstream 저장소의 최신 버전 (괄호는 app version)
* ✅ 최신 / 빈칸 업그레이드 가능 / 🔒 잠금 / ⚪ 비활성

바로 갱신하려면 수동으로 돌린다.

```bash
cat config/repos.txt | xargs -I {} bash -c 'helm repo add {}'
helm repo update

./scripts/update_versions.py
```

`karpenter` 처럼 `public.ecr.aws` 의 OCI chart 를 조회하려면 로그인이 필요하다.
CI 는 익명으로 조회를 시도하고, 실패하면 해당 chart 만 건너뛴다.

```bash
aws ecr-public get-login-password --region us-east-1 | helm registry login --username AWS --password-stdin public.ecr.aws
```

<!--- BEGIN_VERSION --->
| NAME | | CURRENT | LATEST |
| --- | - | --- | --- |
| alloy | ✅ | 1.12.1 | 1.12.1 (v1.19.2) |
| argo-cd |  | 10.9.1 | 10.9.2 (v3.5.3) |
| argo-rollouts |  | 2.43.1 | 2.43.2 (v1.10.0) |
| argo-workflows |  | 2.0.6 | 2.0.8 (v4.1.4) |
| atlantis |  | 6.15.1 | 6.16.0 (v0.48.0) |
| cert-manager | ✅ | v1.21.2 | v1.21.2 (v1.21.2) |
| external-dns | ✅ | 1.22.0 | 1.22.0 (0.22.0) |
| external-secrets |  | 2.10.0 | 2.11.0 (v2.11.0) |
| grafana | ✅ | 10.5.15 | 10.5.15 (12.3.1) |
| istio |  | 1.30.4 | 1.30.5 (1.30.5) |
| kite | ✅ | 0.15.1 | 0.15.1 (v0.15.1) |
| loki | ✅ | 7.3.0 | 7.3.0 (3.6.12) |
| metrics-server | ✅ | 3.14.0 | 3.14.0 (0.9.0) |
| oauth2-proxy | ✅ | 10.7.0 | 10.7.0 (7.15.3) |
| prometheus-adapter | ✅ | 5.3.0 | 5.3.0 (v0.12.0) |
| prometheus-stack |  | 91.4.1 | 91.5.0 (v0.94.0) |
| victoria-metrics |  | 0.90.2 | 0.93.0 (v1.152.0) |
| vllm-stack |  |  | 0.1.12 |
<!--- END_VERSION --->
