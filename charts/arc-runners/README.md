# arc-runners

GitHub `opspresso` 조직의 self-hosted runner scale set `eks-arm64`를 배포한다. Actions Runner Controller(ARC)
controller는 `charts/arc-controller`(namespace `addon-arc-controller`)이고, runner Pod는 namespace `addon-arc-runners`에서 실행한다.

## 사용

workflow job에서 scale set 이름으로 선택한다.

```yaml
jobs:
  build:
    runs-on: eks-arm64
```

- runner는 job마다 새 Pod로 시작하고 job이 끝나면 삭제된다. 대기 runner는 없다(`minRunners: 0`).
- 이미지는 `ghcr.io/actions/actions-runner`(Ubuntu, linux/arm64)다. Node.js·pnpm 같은 도구는 workflow에서 설치한다.
- `docker`는 같은 Pod의 privileged dind sidecar(`docker:<version>-dind`)를 쓴다. image build, `kind`, test container가 여기서 실행된다.
- `linux/amd64` 이미지는 QEMU 에뮬레이션으로 빌드한다. 먼저 `docker run --privileged --rm tonistiigi/binfmt --install amd64`를 실행한다.
- Pod 하나는 runner 2 CPU·6Gi, dind 1.5 CPU·8Gi를 요청한다. 작업 디렉터리와 Docker 저장소는 노드 disk의 emptyDir이며 job마다 비워진다.
- public 저장소는 조직 `Default` runner group 설정상 이 runner를 쓰지 않는다.

## 노드

runner Pod는 Karpenter NodePool `gha-runners`(`terraform-env-demo` `demo/6-eks-node/63-gha-runners.tf`)에만 배치된다.
job이 있으면 8-CPU Graviton m 노드(Spot 우선)를 만들고, 비면 10분 뒤 회수한다. `maxRunners`는 Terraform 변수
`gha_runner_max_runners`와 같게 유지한다. Spot 회수가 일어나면 실행 중인 job은 실패하므로 다시 실행한다.

## 인증

GitHub App `opspresso-arc`(조직 권한 Self-hosted runners: Read and write, Metadata: Read)가 `opspresso` 조직의 모든 저장소에 설치돼 있다.
ExternalSecret `arc-github-app`이 다음 SSM 파라미터로 Secret을 만든다.

| 파라미터 | 형식 | 용도 |
| --- | --- | --- |
| `/k8s/common/github/opspresso-arc/app_id` | String | GitHub App ID |
| `/k8s/common/github/opspresso-arc/installation_id` | String | `opspresso` 조직 설치 ID |
| `/k8s/common/github/opspresso-arc/private_key` | SecureString | GitHub App private key(PEM) |

private key를 교체하면 GitHub App 설정에서 새 key를 만들고 `private_key`를 갱신한 뒤 이전 key를 삭제한다.
ExternalSecret은 1시간마다 갱신하며, 즉시 반영하려면 ExternalSecret에 `force-sync` annotation을 바꾼다.

## 확인

```bash
kubectl -n addon-arc-controller get pods           # controller, eks-arm64 listener
kubectl -n addon-arc-runners get autoscalingrunnersets,ephemeralrunners
kubectl get nodeclaims -l karpenter.sh/nodepool=gha-runners
```

listener가 `Running`이고 AutoscalingRunnerSet의 상태에 오류가 없으면 GitHub 조직 설정의 Runners 목록에 `eks-arm64`가 보인다.
