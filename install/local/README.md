# 로컬 Kubernetes 개발 환경

기존 k3s와 같은 GitOps 구조에 `local-demo` 환경을 추가한다. Argo CD·External Secrets는
`argocd-env-addons`, PostgreSQL·MinIO·Neo4j·MCP 5종은 `argocd-env-demo`가 관리한다.
OrbStack과 Docker Desktop은 이 `local` 환경을 실행하는 Kubernetes 제품이다.
Studio·Memory는 Mac에서 `pnpm`으로 실행한다. namespace와 Helm release는 모든 환경에서 `argocd`다.

## 구성

| 구분 | 경로·namespace |
| --- | --- |
| 클러스터 값 | 두 저장소의 `env/local-demo.yaml` |
| Addons 루트 | `addons-local.yaml` → `addons/local/` |
| Apps 루트 | `apps-local.yaml` → `apps/local/` |
| Argo CD | `argocd` |
| External Secrets | `addon-external-secrets` |
| PostgreSQL·MinIO | `agent-studio` |
| Neo4j | `agent-memory` |
| MCP 5종 | `agent-mcps` |

기존 chart를 재사용하고 `values-template.yaml.j2`에서 `local/values-local-demo.yaml`을 생성한다.
MCP의 values 순서는 `values.yaml` → `values-alpha.yaml` → `local/values-local-demo.yaml`이다.
데이터 차트는 기존 k3s처럼 phase 값 없이 공통 값과 클러스터 값만 병합한다.
Application은 `argocd` namespace의 `addons`, `apps` 프로젝트에서 관리한다.
workload namespace와 자동 동기화 설정은 기존 k3s 구성을 따른다.
Argo CD 자체는 Helm release `argocd`로 관리하며 `addons-local`의 자동 동기화 대상에서 제외한다.

Argo CD는 controller·server·repo-server·Redis만 각 1개 실행한다. Dex·notifications·
ApplicationSet controller와 ingress·인증서·모니터링은 사용하지 않는다. External Secrets는
기존 controller·webhook·certController 구성을 유지한다. 데이터 서비스와 MCP는 각 1개이며
MinIO의 별도 console Pod는 끈다. PostgreSQL·MinIO·Neo4j의 PVC 요청은 각각 5Gi다.
k3s·local은 `resources.enabled: false`(addons), `resources: false`(apps)와
`autoscaling.enabled: false`(addons), `autoscaling: false`(apps)를 사용한다.
CPU·메모리 requests/limits와 autoscaler를 선언하지 않는다. PVC의 storage 요청과 Neo4j JVM 설정은 별도로 유지한다.

## 자격 증명

기존 `parameter-store` ClusterSecretStore와 AWS SSM을 사용한다. 다음 파라미터를 준비한다.

| SSM 경로 | 내용 |
| --- | --- |
| `/k8s/common/*` | 새 Argo CD 설치의 관리자 비밀번호, Brave key, 기존 Grafana 관리자 계정 |
| `/k8s/local-demo/agent-studio/postgres-password` | 공유 PostgreSQL의 `agent_studio` 사용자 비밀번호 |
| `/k8s/local-demo/agent-studio/minio-root-user` | MinIO 사용자 |
| `/k8s/local-demo/agent-studio/minio-root-password` | MinIO 비밀번호 |
| `/k8s/local-demo/agent-memory/neo4j-auth` | `neo4j/PASSWORD` 형식 |
| `/k8s/local-demo/mcp-argocd/argocd-api-token` | 기존 로컬 Argo CD의 읽기 전용 `mcp` 계정 토큰 |

Grafana MCP 대상은 apps 저장소 `env/local-demo.yaml`의 `grafana_url`이다. 기본값은 기존
AWS k3s의 `https://grafana.demo.opsp.dev`이며, 기존 common Grafana 계정을 사용한다.

로컬 Argo CD는 기존 서명 키·관리자 비밀번호·`mcp` 계정 권한을 유지한다.
MCP에는 해당 로컬 계정의 토큰을 사용하며, 다른 Argo CD 인스턴스의 공통 토큰을 연결하지 않는다.
`install/eks/token.sh`는 공통 Argo CD 토큰의 관리 절차이므로 로컬 인증 설정을 바꾸는 데 사용하지 않는다.

설치 스크립트의 AWS CLI는 로컬 credential chain을 사용한다. External Secrets와
CloudWatch MCP도 로컬 `~/.aws/config`, `~/.aws/credentials`를 읽기 전용 `hostPath`로
연결하고 AWS SDK의 기본 credential chain으로 같은 프로필을 사용한다. AWS 키를
내보내거나 Kubernetes Secret으로 복사하지 않는다.

두 저장소의 `env/local-demo.yaml`에 있는 `aws_local`은 프로필 이름과 파일 경로만 가진다.
현재 로컬 프로필은 `default`다. 다른 프로필이나 파일을 사용할 때는 두 env의
`profile`, `config_file`, `credentials_file`을 로컬 AWS CLI 설정과 일치시킨 뒤 재생성한다.
`config_file`, `credentials_file`은 Kubernetes 노드에서 접근 가능한 파일 경로다. Docker Desktop의
파일 공유에 해당 디렉터리를 포함하고, 사용하는 Kubernetes provisioner의 hostPath 경로와 맞춘다.
실제 자격 증명과 파일 권한은 로컬에서 관리하며, 컨테이너의 기본 사용자도 유지한다.
EKS·k3s는 기존 Pod Identity·instance profile 등 실행 환경의 SDK credential chain을 사용한다.

공유 파일 설정은 [AWS SDK 공식 문서](https://docs.aws.amazon.com/sdkref/latest/guide/file-format.html)를 따른다.

## 설치

OrbStack 또는 Docker Desktop의 Kubernetes, Helm, AWS CLI와 두 저장소의 Python requirements를 준비한다.
PVC는 선택한 클러스터의 기본 StorageClass를 사용한다.
두 저장소의 local 변경이 GitOps의 `HEAD`에서 조회 가능해야 한다.

각 저장소에서 클러스터 값을 생성·검증한다.

```bash
# argocd-env-addons
GITHUB_PUSH=false bash build.sh
python3 validate.py -d addons/local

# argocd-env-demo
GITHUB_PUSH=false bash build.sh
python3 validate.py -d apps/local
```

addons 저장소에서 실행 제품에 맞는 context를 지정한다. 생략하면 현재 context를 사용하지만,
`orbstack`과 `docker-desktop` 외의 context는 변경 전에 거부한다. 모든 명령에 선택한 context를 전달한다.

```bash
KUBE_CONTEXT=orbstack bash install/local/install.sh
# Docker Desktop을 사용할 때
KUBE_CONTEXT=docker-desktop bash install/local/install.sh
```

기존 `argocd` Helm release가 있으면 재설치와 관리자 자격 증명 변경을 건너뛴다.
새 설치에서만 로컬 AWS 권한으로 SSM 관리자 계정을 조회해 bootstrap한다.
이후 로컬 `addons`, `apps` AppProject와 `addons-local`, `apps-local`를 등록한다. External Secrets와
데이터·MCP workload는 등록된 GitOps Application이 동기화한다.

## Mac 접속과 앱 실행

두 실행 환경의 공통 접속 경로는 localhost 포트 포워딩이다. 별도 터미널에서 연결을 유지한다.
`--context`를 생략하면 설치와 같은 context 선택 규칙을 사용한다.

```bash
python3 install/local/connect.py --context orbstack
# 또는 --context docker-desktop
```

`--list`는 주소만 출력하고, `--only argocd`처럼 일부 서비스만 선택할 수 있다. 기존 프로세스가
사용하는 포트는 덮어쓰지 않는다. Ctrl-C는 이 명령이 연 포워딩을 함께 종료한다. Pod 교체나
연결 단절로 포워딩이 끝나면 원인을 표시하고 종료하므로 Pod가 준비된 뒤 다시 실행한다.
포트와 Service 매핑의 원천은 `connections.yaml`이다.

| 대상 | Mac에서 사용하는 주소 |
| --- | --- |
| Argo CD | `http://localhost:8080` |
| PostgreSQL | `localhost:5432` |
| S3 | `http://localhost:9000` |
| Neo4j Bolt / Browser | `bolt://localhost:7687` / `http://localhost:7474` |
| Argo CD MCP | `http://localhost:8081/mcp` |
| Brave Search MCP | `http://localhost:8082/mcp` |
| CloudWatch MCP | `http://localhost:8083/mcp` |
| Kubernetes MCP | `http://localhost:8084/mcp` |
| Grafana MCP | `http://localhost:8000/mcp` |
| Studio / Memory | `http://localhost:3000` / `http://localhost:3100` |

`agent-studio.env.example`, `agent-memory.env.example`의 연결 값을 각 앱의 `.env.local`에
반영하고 자격 증명은 위 SSM 값과 맞춘다. 기존 인증·암호화·모델 설정은 유지한다.
PostgreSQL 사용자 `agent_studio`가 `agent_studio`, `agent_memory` database를 사용하며,
MinIO bucket도 두 앱 이름으로 나눈다. Agent Studio는 이 저장소에서 실행하지 않고 앱 저장소에서 실행한다.

```bash
# agent-studio 저장소
pnpm dev
```

Mac의 MCP 클라이언트에는 위 localhost URL을 등록하고, Studio의
`MCP_INTERNAL_HOST_SUFFIXES`에 `localhost`를 포함한다. Kubernetes 안의 클라이언트는 기존
`http://mcp-<name>.agent-mcps.svc.cluster.local/mcp`를 사용한다. 내부 DNS를 담은 plugin 정의는
Docker Desktop의 Mac 호스트용 URL이 아니므로 로컬 연결 URL과 구분한다.

OrbStack에서는 [Service DNS 직접 연결](https://docs.orbstack.dev/kubernetes/#services)도 가능하다.
Docker Desktop과 설정을 공유하려면 위 localhost 주소를 사용한다.

## Argo CD 접속

포워딩을 시작하고 `http://localhost:8080`에 접속한다. 기존 관리자 계정은
`admin`이며 초기 비밀번호를 변경하지 않았다면 다음 명령으로 확인한다. 비밀번호를 문서나
Git에 저장하지 않는다.

```bash
kubectl --context orbstack -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 --decode
```
