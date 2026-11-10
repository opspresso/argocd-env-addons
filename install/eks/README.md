# EKS 설치

관리 클러스터 `eks-demo`에 Argo CD를 설치하고 addons·apps를 등록한다. SSM이 비어 있는 계정과 값이 이미 있는 계정에서
같은 명령으로 실행한다. 여러 번 실행해도 있는 값과 설치 상태를 바꾸지 않는다.

## 사전 조건

1. EKS 클러스터가 있다(`terraform-env-demo`의 `demo/5-eks`). `kubectl` context가 이 클러스터를 가리킨다.
2. AWS 자격 증명에 SSM Parameter Store 읽기·쓰기 권한이 있다.
3. 다음 명령이 있다: `aws`, `jq`, `kubectl`, `helm`, `openssl`, `uuidgen`, `python3`.
4. Python 의존성(PyYAML, bcrypt)을 설치한다.

   ```bash
   python3 -m pip install -r ../../requirements/runtime.txt
   ```

5. 선택: 관리자 비밀번호를 정하려면 설치 전에 `/k8s/common/admin-password`를 넣는다. 넣지 않으면 무작위 24자가 생긴다.

## 설치

```bash
cd install/eks
./install.sh
```

`install.sh`는 다음을 차례로 실행한다. 한 단계라도 실패하면 그 단계 이름과 종료 코드를 출력하고 멈춘다.
값은 출력하지 않는다. 원인을 고친 뒤 다시 실행하면 이어서 진행한다.

1. `env/eks-demo.yaml`에서 Argo CD 주소(`argocd.hostname`)를 읽는다.
2. `token.sh`, `token.sh --account keep`: Argo CD 서명 키와 `mcp`·`keep` 계정 토큰을 확인하거나 만든다.
3. `secrets.sh`: 관리자 계정과 addon이 읽는 무작위 값을 없을 때만 만든다. 외부 발급 값이 없으면 경고한다.
4. `build.sh`: env 설정과 SSM 값으로 `values.output.yaml`(0600)을 만든다. 조회가 하나라도 실패하면 기존 파일을 유지한다.
5. `helm upgrade --install argocd`: Argo CD를 설치하고 준비될 때까지 기다린다(`HELM_TIMEOUT`, 기본 10m).
6. `bootstrap.yaml`: 클러스터를 이름 `eks-demo`로 등록하는 cluster Secret과 `addons`·`apps` AppProject를 적용한다.
7. `addons-eks.yaml`과 `argocd-env-apps`의 `apps-eks.yaml`을 등록한다.

설치는 공개 DNS·로그인·`argocd` CLI를 쓰지 않는다. 부트스트랩 Argo CD는 Ingress를 만들지 않고 로컬 `admin`으로만 로그인한다.

### 결과 확인

1. addons가 동기화될 때까지 기다린다. `argo-cd` addon은 자동 sync이며 Argo CD가 자기 chart를 sync한다.

   ```bash
   kubectl -n argocd get applications
   ```

2. `istio`와 `argo-cd` addon이 동기화되면 `https://<argocd.hostname>`이 공용 ALB와 istio HTTPRoute로 응답한다.
   도메인은 `terraform-env-demo`의 `3-alb`(`*.demo.opsp.dev`)가 소유한다.
3. `lldap` addon이 동기화되면 LLDAP 로그인(Dex connector `lldap`)이 동작한다. 관리자 아이디·비밀번호는 다음 값이다.

   ```bash
   aws ssm get-parameter --name /k8s/common/admin-user --with-decryption --query Parameter.Value --output text
   aws ssm get-parameter --name /k8s/common/admin-password --with-decryption --query Parameter.Value --output text
   ```

4. 첫 sync에서 Dex가 Secret `argocd-dex-lldap`보다 먼저 시작하면 LLDAP 로그인이 실패한다.
   그때는 `kubectl -n argocd rollout restart deploy/argocd-dex-server`를 실행한다.

apps(`argocd-env-apps`)가 읽는 SSM 값은 이 설치가 만들지 않는다. 각 앱 chart의 문서를 따른다.

## SSM 파라미터

클러스터 설정(Argo CD 주소, 관리자 그룹)은 SSM이 아니라 `env/eks-demo.yaml`의 `argocd.hostname`, `sso.admin_groups`에 있다.

| 종류 | 파라미터 | 만드는 곳 |
| --- | --- | --- |
| 관리자 | `/k8s/common/admin-user`(기본 `admin`), `admin-password`(무작위 24자) | `secrets.sh` |
| 관리자 해시 | `/k8s/common/argocd-password`(`admin-password`의 bcrypt), `argocd-mtime` | `secrets.sh` |
| 서명 키·토큰 | `/k8s/common/argocd-server-secret`, `argocd-<계정>-tokens`, 계정 토큰 | `token.sh` |
| 무작위 값 | webhook, OIDC client secret, cookie, DB 비밀번호, 암호화 키 | `secrets.sh` |
| 외부 발급 값 | 아래 '외부 발급 값' | 사람 |

- Argo CD·LLDAP·Grafana 관리자가 `admin-user`·`admin-password`를 함께 쓴다.
- 만드는 값은 없을 때만 만들고 있는 값은 바꾸지 않는다. DB 비밀번호나 암호화 키를 바꾸면 기존 데이터를 읽을 수 없기 때문이다.
- 예외는 `argocd-password`와 `argocd-mtime`이다. `admin-password`와 맞지 않으면 다시 만든다. 관리자 세션은 끊긴다.
- `ParameterNotFound`만 없는 값으로 처리한다. 권한·통신 오류가 나면 그 파라미터를 쓰기 전에 멈춘다.
- 배포 addon이 읽는 파라미터는 모두 위 단계가 만들거나 외부 발급 값으로 등록돼 있다(`tests/test_empty_ssm.py`가 검사).
  addon이 새 파라미터를 읽으면 `secrets.sh`에 생성을 추가하거나 외부 발급 값에 등록한다.

`secrets.sh`는 따로 실행할 수도 있다.

```bash
./secrets.sh           # 없는 값을 만든다. admin-password를 바꾼 뒤 관리자 해시를 맞출 때도 쓴다
./secrets.sh --check   # 만들지 않고 없는 값만 출력한다. 만들 값이 있으면 종료 코드 1
```

### 외부 발급 값

`secrets.sh`는 만들지 않고, 없으면 영향받는 addon과 함께 경고한다. 설치는 계속되며 표의 기능만 동작하지 않는다.
값을 넣은 뒤 해당 addon을 다시 sync한다.

| 파라미터 | 없을 때 | 발급 |
| --- | --- | --- |
| `/k8s/common/github/opspresso-arc/app_id`, `installation_id`, `private_key` | `arc-runners` 미동작 | GitHub App(`charts/arc-runners/README.md`) |
| `/k8s/common/keep/slack-bot-token` | `keep` 미동작 | Slack 앱(`charts/keep/README.md`) |

```bash
aws ssm put-parameter --name /k8s/common/keep/slack-bot-token --value "<xoxb-...>" --type SecureString
```

GitHub 로그인은 꺼져 있다. 다시 켜려면 `charts/argo-cd`의 connector `github`·`argocd-dex-github`와
`env/eks-demo.yaml`의 GitHub 팀 주석을 풀고, GitHub OAuth App(callback `https://<argocd.hostname>/api/dex/callback`)의
값을 `/k8s/<argocd.github.org>/argocd-github-id`·`argocd-github-secret`에 넣는다.

## Server secret and API tokens

`install.sh`가 실행하므로 보통 따로 실행하지 않는다.

```bash
./token.sh                  # mcp 계정. 없거나 무효일 때만 발급 (여러 번 실행해도 안전)
./token.sh --account keep   # Keep argocd provider 의 keep 계정
./token.sh --rotate         # 토큰만 새로 발급. 이전 토큰은 즉시 무효
```

| 파라미터 | 읽는 곳 |
|---|---|
| `/k8s/common/argocd-server-secret` | `argocd-secret`의 `server.secretkey`. **없을 때만** 만든다 (32 bytes, hex) |
| `/k8s/common/argocd-mcp-tokens`, `argocd-keep-tokens` | `argocd-secret`의 `accounts.<계정>.tokens`(`values.yaml`, `charts/argo-cd`의 ExternalSecret) |
| `/k8s/common/mcp-argocd/argocd-api-token` | mcp-argocd 파드의 `ARGOCD_API_TOKEN`(argocd-env-apps) |
| `/k8s/common/keep/argocd-api-token` | Keep argocd provider |

Argo CD는 API 토큰을 `server.secretkey`로 서명하고, `jti`가 계정의 토큰 목록에 있는지 확인한다
(argoproj/argo-cd `util/session/sessionmanager.go`). 키와 목록을 SSM에 고정하므로 클러스터를 다시 만들어도 같은 토큰이 통한다.
`argocd account generate-token`은 목록을 클러스터 안 `argocd-secret`에만 남기고, ExternalSecret이 다음 갱신 때 지우므로 쓰지 않는다.

- **`argocd-server-secret`은 이미 있으면 바꾸지 않는다.** 바꾸면 발급된 토큰과 로그인 세션이 모두 무효가 된다.
- 토큰을 폐기하려면 `./token.sh --rotate`로 바꾸거나, 토큰 목록 파라미터를 `[]`로 되돌린다.

## 삭제

Argo CD와 addons는 클러스터와 함께 삭제한다. SSM 값은 남으므로 같은 계정에 다시 설치하면 같은 관리자·토큰·키를 쓴다.

```bash
terraform destroy   # terraform-env-demo demo/5-eks
```
