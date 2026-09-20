# OrbStack 개발 환경

기존 k3s와 같은 GitOps 구조에 `orb-demo` 환경을 추가한다. Argo CD·External Secrets는
`argocd-env-addons`, PostgreSQL·MinIO·Neo4j·MCP 5종은 `argocd-env-demo`가 관리한다.
Studio·Memory는 Mac에서 `pnpm`으로 실행한다.

## 구성

| 구분 | 경로·namespace |
| --- | --- |
| 클러스터 값 | 두 저장소의 `env/orb-demo.yaml` |
| Addons 루트 | `addons-orb.yaml` → `addons/orb/` |
| Apps 루트 | `apps-orb.yaml` → `apps/orb/` |
| Argo CD | `argocd` |
| External Secrets | `addon-external-secrets` |
| PostgreSQL·MinIO | `agent-studio` |
| Neo4j | `agent-memory` |
| MCP 5종 | `agent-mcps` |

기존 chart를 재사용하고 `values-template.yaml.j2`에서 `orb/values-orb-demo.yaml`을 생성한다.
MCP의 values 순서는 `values.yaml` → `values-alpha.yaml` → `orb/values-orb-demo.yaml`이다.
데이터 차트는 기존 k3s처럼 phase 값 없이 공통 값과 클러스터 값만 병합한다.
Application 이름·자동 동기화·namespace는 기존 k3s 구성을 따른다.

Argo CD는 controller·server·repo-server·Redis만 각 1개 실행한다. Dex·notifications·
ApplicationSet controller와 ingress·인증서·모니터링은 사용하지 않는다. External Secrets는
기존 controller·webhook·certController 구성을 유지한다. 데이터 서비스와 MCP는 각 1개이며
MinIO의 별도 console Pod는 끈다. PostgreSQL·MinIO·Neo4j의 PVC 요청은 각각 5Gi다.
k3s·orb는 `resources.enabled: false`(addons), `resources: false`(apps)와
`autoscaling.enabled: false`(addons), `autoscaling: false`(apps)를 사용한다.
CPU·메모리 requests/limits와 autoscaler를 선언하지 않는다. PVC의 storage 요청과 Neo4j JVM 설정은 별도로 유지한다.

## 자격 증명

기존 `parameter-store` ClusterSecretStore와 AWS SSM을 사용한다. 다음 파라미터를 준비한다.

| SSM 경로 | 내용 |
| --- | --- |
| `/k8s/common/*` | 기존 Argo CD 관리자·서명 키·MCP token·Brave key 등의 공통 값 |
| `/k8s/orb-demo/agent-studio/postgres-password` | 공유 PostgreSQL의 `agent_studio` 사용자 비밀번호 |
| `/k8s/orb-demo/agent-studio/minio-root-user` | MinIO 사용자 |
| `/k8s/orb-demo/agent-studio/minio-root-password` | MinIO 비밀번호 |
| `/k8s/orb-demo/agent-memory/neo4j-auth` | `neo4j/PASSWORD` 형식 |
| `/k8s/orb-demo/mcp-grafana/url` | 접속할 기존 Grafana URL |
| `/k8s/orb-demo/mcp-grafana/service-account-token` | 해당 Grafana의 service account token |

공통 Argo CD token의 준비·관리 규칙은 `install/eks/token.sh`와 기존 Argo CD 차트 문서를
따른다. OrbStack용 token 발급이나 로컬 비밀번호 생성 절차를 별도로 만들지 않는다.

설치 스크립트의 AWS CLI는 로컬 credential chain을 사용한다. External Secrets와
CloudWatch MCP도 로컬 `~/.aws/config`, `~/.aws/credentials`를 읽기 전용 `hostPath`로
연결하고 AWS SDK의 기본 credential chain으로 같은 프로필을 사용한다. AWS 키를
내보내거나 Kubernetes Secret으로 복사하지 않는다.

두 저장소의 `env/orb-demo.yaml`에 있는 `aws_local`은 프로필 이름과 파일 경로만 가진다.
현재 로컬 프로필은 `default`다. 다른 프로필이나 파일을 사용할 때는 두 env의
`profile`, `config_file`, `credentials_file`을 로컬 AWS CLI 설정과 일치시킨 뒤 재생성한다.
실제 자격 증명과 파일 권한은 로컬에서 관리하며, 컨테이너의 기본 사용자도 유지한다.
EKS·k3s는 기존 Pod Identity·instance profile 등 실행 환경의 SDK credential chain을 사용한다.

공유 파일 설정은 [AWS SDK 공식 문서](https://docs.aws.amazon.com/sdkref/latest/guide/file-format.html)를 따른다.

## 설치

OrbStack Kubernetes, Helm, AWS CLI와 두 저장소의 Python requirements를 준비한다.
두 저장소의 orb 변경이 GitOps의 `HEAD`에서 조회 가능해야 한다.

각 저장소에서 클러스터 값을 생성·검증한다.

```bash
# argocd-env-addons
GITHUB_PUSH=false bash build.sh
python3 validate.py -d addons/orb

# argocd-env-demo
GITHUB_PUSH=false bash build.sh
python3 validate.py -d apps/orb
```

addons 저장소에서 설치한다. 모든 cluster 접근은 `orbstack` context를 명시한다.

```bash
bash install/orb/install.sh
kubectl --context orbstack -n argocd get applications
```

설치 순서는 로컬 AWS 권한으로 SSM 관리자 계정 조회 → Argo CD bootstrap →
기존 `addons`, `apps` AppProject → `addons-orb`, `apps-orb` 등록이다. External Secrets와
데이터·MCP workload는 등록된 GitOps Application이 동기화한다.

## 앱 실행

`agent-studio.env.example`, `agent-memory.env.example`의 연결 값을 각 앱의 `.env.local`에
반영하고 비밀번호는 위 SSM 파라미터와 맞춘다. 기존 인증·암호화·모델 설정은 유지한다.
PostgreSQL 사용자는 k3s와 같이 `agent_studio`이며 database는 `agent_studio`, `agent_memory`로
나눈다. MinIO bucket은 `agent-studio`, `agent-memory`를 사용한다.

각 앱 저장소에서 별도 터미널로 실행한다.

```bash
# agent-studio
pnpm dev

# agent-memory
pnpm db:init
pnpm dev
```

| 대상 | Mac에서 사용하는 주소 |
| --- | --- |
| Argo CD | `http://argocd-server.argocd.svc.cluster.local` |
| PostgreSQL | `postgres.agent-studio.svc.cluster.local:5432` |
| S3 | `http://minio.agent-studio.svc.cluster.local:9000` |
| Neo4j Bolt | `bolt://memory-neo4j.agent-memory.svc.cluster.local:7687` |
| MCP | `http://mcp-<name>.agent-mcps.svc.cluster.local/mcp` |
| Studio / Memory | `http://localhost:3000` / `http://localhost:3100` |

[OrbStack Service 직접 연결](https://docs.orbstack.dev/kubernetes/#services)을 사용하므로
port-forward가 필요하지 않다. MCP는 기존 plugin의 주소를 그대로 사용한다.
