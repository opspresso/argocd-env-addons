# argocd

* <https://argo-cd.readthedocs.io/en/stable/getting_started/>
* <https://argocd-applicationset.readthedocs.io/en/stable/Getting-Started/>

## Create eks cluster

* <https://github.com/opspresso/terraform-env-demo/tree/main/demo/5-eks>

```bash
terraform apply
```

## SSM parameters

`./install.sh`는 SSM이 비어 있는 계정과 값이 이미 있는 계정에서 같은 명령으로 실행한다.
만들 수 있는 값은 없을 때만 만들고, 있는 값은 바꾸지 않는다. 클러스터 설정(Argo CD 주소,
관리자 그룹)은 SSM이 아니라 `env/<cluster>.yaml`의 `argocd.hostname`,
`sso.admin_groups`에서 읽는다.

| 종류 | 파라미터 | 만드는 곳 |
| --- | --- | --- |
| 관리자 | `/k8s/common/admin-user`(기본 `admin`), `admin-password`(무작위 24자) | `secrets.sh` |
| 관리자 해시 | `/k8s/common/argocd-password`(`admin-password`의 bcrypt), `argocd-mtime` | `secrets.sh` |
| 서명 키·토큰 | `/k8s/common/argocd-server-secret`, `argocd-<계정>-tokens`, 각 계정 토큰 | `token.sh` |
| 무작위 값 | webhook, OIDC client secret, cookie, DB 비밀번호, 암호화 키 | `secrets.sh` |
| 외부 발급 값 | 아래 'External values' | 사람 |

- 관리자 비밀번호를 정하려면 설치 전에 `/k8s/common/admin-password`를 넣는다. 넣지 않으면 무작위 값이 생긴다.
  Argo CD·LLDAP·Grafana 관리자가 같은 값을 쓴다.

  ```bash
  aws ssm get-parameter --name /k8s/common/admin-password --with-decryption --query Parameter.Value --output text
  ```

- `admin-password`를 바꾼 뒤 `./secrets.sh`를 실행하면 `argocd-password`와 `argocd-mtime`을 다시 만든다.
  이 둘은 `secrets.sh`가 덮어쓰는 유일한 값이다. 관리자 세션은 끊긴다.

### External values

밖에서 발급하는 값이다. `secrets.sh`는 만들지 않고, 없으면 경고만 출력한다. 설치는 계속되며 표의 기능만 동작하지 않는다.
값을 넣은 뒤 해당 addon을 다시 sync한다.

| 파라미터 | 없을 때 | 발급 |
| --- | --- | --- |
| `/k8s/common/github/opspresso-arc/app_id`, `installation_id`, `private_key` | `arc-runners` 미동작 | GitHub App |
| `/k8s/common/keep/slack-bot-token` | `keep` 미동작 | Slack app (`charts/keep/README.md`) |

```bash
aws ssm put-parameter --name /k8s/common/keep/slack-bot-token --value "<xoxb-...>" --type SecureString
```

GitHub 로그인은 꺼져 있다. 다시 켜려면 `charts/argo-cd`의 connector `github`·`argocd-dex-github`와
`env/<cluster>.yaml`의 GitHub 팀 주석을 풀고, GitHub OAuth App(callback `https://<argocd-hostname>/api/dex/callback`)의
값을 `/k8s/<argocd.github.org>/argocd-github-id`·`argocd-github-secret`에 넣는다.

## Server secret and API tokens

`install.sh`가 실행하므로 보통 따로 실행하지 않는다.

```bash
./token.sh                  # 없거나 무효일 때만 발급 (여러 번 실행해도 안전)
./token.sh --account keep   # Keep argocd provider 의 keep 계정
./token.sh --rotate         # 토큰만 새로 발급. 이전 토큰은 즉시 무효
```

| 파라미터 | 읽는 곳 |
|---|---|
| `/k8s/common/argocd-server-secret` | argocd-secret 의 `server.secretkey` — **없을 때만** 만든다 (32 bytes, hex) |
| `/k8s/common/argocd-mcp-tokens`, `argocd-keep-tokens` | argocd-secret 의 `accounts.<계정>.tokens` — `install/eks/values.yaml`과 `charts/argo-cd`의 ExternalSecret |
| `/k8s/common/mcp-argocd/argocd-api-token` | mcp-argocd 파드의 `ARGOCD_API_TOKEN` (argocd-env-apps) |
| `/k8s/common/keep/argocd-api-token` | Keep argocd provider |

Argo CD 는 API 토큰을 `server.secretkey`로 서명하고, `jti`가 계정의 토큰 목록에 있는지 확인한다.
키와 목록을 SSM에 고정하므로 클러스터를 다시 만들어도 같은 토큰이 통한다.
`argocd account generate-token`은 목록을 클러스터 안에만 남기기 때문에 쓰지 않는다.
**`argocd-server-secret`은 이미 있으면 바꾸지 않는다.** 바꾸면 발급된 토큰과 로그인 세션이 모두 무효가 된다.

## Install Argo CD and register addons

Python 3와 PyYAML·bcrypt가 필요하다. `install/eks/`에서 다음 명령으로 실행 의존성을 설치한다.

```bash
python3 -m pip install -r ../../requirements/runtime.txt
```

`./install.sh`는 다음을 차례로 실행한다. 한 단계라도 실패하면 그 단계 이름과 종료 코드를 출력하고 멈춘다.

1. `env/<cluster>.yaml`(`CLUSTER`, 기본 `eks-demo`)에서 Argo CD 주소를 읽는다.
2. `token.sh`: Argo CD 서명 키와 mcp·keep 계정 토큰을 SSM에서 확인하거나 만든다.
3. `secrets.sh`: 관리자 계정과 addon이 읽는 무작위 값을 없을 때만 SSM에 만든다(아래 'Addon secrets').
4. `build.sh`: env 설정과 SSM 값으로 `values.output.yaml`(0600)을 만든다. 부트스트랩은 관리자 계정으로만
   로그인한다. 값 조회가 하나라도 실패하면 기존 파일을 유지한다.
5. `helm upgrade --install argocd`: Argo CD를 설치하고 준비될 때까지 기다린다(`HELM_TIMEOUT`, 기본 10m).
6. `bootstrap.yaml`: 이 클러스터를 이름 `eks-demo`로 등록하는 cluster Secret과 `addons`·`apps` AppProject를 적용한다.
7. `addons-eks.yaml`과 `argocd-env-apps`의 `apps-eks.yaml`을 등록한다.

설치는 공개 DNS·로그인·`argocd` CLI를 사용하지 않는다. 부트스트랩 values는 Ingress를 만들지 않는다.
Argo CD UI(`https://<argocd-hostname>`)는 `istio`와 `argo-cd` addon이 동기화된 뒤 공용 ALB와
istio HTTPRoute로 응답한다. 도메인은 `terraform-env-demo`의 `3-alb`(`*.demo.opsp.dev`)가 소유한다.
`argo-cd` addon은 자동 sync다. `addons-eks.yaml`이 동기화되면 Argo CD가 자기 chart를 따로 sync한다.

```bash
./install.sh
```

## Addon secrets

`./secrets.sh`는 관리자 계정과 addon이 읽는 무작위 값(OIDC client secret, DB 비밀번호, 암호화 키)을
SSM에 만든다. **없는 파라미터만 만들고 있는 값은 바꾸지 않는다.** DB 비밀번호나 암호화 키를 바꾸면 기존 데이터를 읽을 수 없기 때문이다.
`install.sh`가 Argo CD 설치 전에 실행한다. `argocd-secret`이 OIDC client secret을 읽으므로 하나라도 없으면 Argo CD가 시작하지 않는다.

```bash
./secrets.sh           # 없는 값만 만든다
./secrets.sh --check   # 만들지 않고 없는 값만 출력한다. 하나라도 없으면 종료 코드 1
```

- 값은 출력하지 않는다. `ParameterNotFound`만 미생성으로 처리하고, 권한·통신 오류는 쓰기 전에 중단한다.
- 밖에서 발급하는 값은 위 'External values'를 따른다.

## Delete

### Delete eks cluster

```bash
terraform destroy
```
