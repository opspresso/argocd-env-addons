# argocd

* <https://argo-cd.readthedocs.io/en/stable/getting_started/>
* <https://argocd-applicationset.readthedocs.io/en/stable/Getting-Started/>

## Create eks cluster

* <https://github.com/opspresso/terraform-env-demo/tree/main/demo/5-eks>

```bash
terraform apply
```

## Set variables

> argocd admin password 를 잊어버리지 않기 위해, aws ssm 에 저장 합니다.
> 사람의 로그인은 Kanidm(`charts/kanidm`)이 맡습니다. 여기서는 GitHub 계정·팀을 설정하지 않습니다.

```bash
# variables
export ARGOCD_HOSTNAME="argocd.demo.opsp.dev"

export ADMIN_USERNAME="admin"
export ADMIN_PASSWORD="REPLACE_ME"

export ARGOCD_PASSWORD="$(htpasswd -nbBC 10 "" ${ADMIN_PASSWORD} | tr -d ':\n' | sed 's/$2y/$2a/')"
export ARGOCD_MTIME="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
export ARGOCD_SERVER_SECRET="REPLACE_ME" # random string. 아래 'Set server secret and mcp token' 참고
export ARGOCD_WEBHOOK="REPLACE_ME" # random string


# put aws ssm parameter store
aws ssm put-parameter --name /k8s/common/argocd-hostname --value "${ARGOCD_HOSTNAME}" --type SecureString --overwrite | jq .

aws ssm put-parameter --name /k8s/common/admin-user --value "${ADMIN_USERNAME}" --type SecureString --overwrite | jq .
aws ssm put-parameter --name /k8s/common/admin-password --value "${ADMIN_PASSWORD}" --type SecureString --overwrite | jq .

aws ssm put-parameter --name /k8s/common/argocd-password --value "${ARGOCD_PASSWORD}" --type SecureString --overwrite | jq .
aws ssm put-parameter --name /k8s/common/argocd-mtime --value "${ARGOCD_MTIME}" --type SecureString --overwrite | jq .
aws ssm put-parameter --name /k8s/common/argocd-server-secret --value "${ARGOCD_SERVER_SECRET}" --type SecureString --overwrite | jq .
aws ssm put-parameter --name /k8s/common/argocd-webhook --value "${ARGOCD_WEBHOOK}" --type SecureString --overwrite | jq .

aws ssm put-parameter --name /k8s/common/argo-workflows-client-secret --value "${ARGOCD_SERVER_SECRET}" --type SecureString --overwrite | jq .
aws ssm put-parameter --name /k8s/common/oauth2-proxy-client-secret --value "${ARGOCD_SERVER_SECRET}" --type SecureString --overwrite | jq .
aws ssm put-parameter --name /k8s/common/cookie-secret --value "${ARGOCD_SERVER_SECRET}" --type SecureString --overwrite | jq .

```

## Set server secret and mcp token

> 위 'Set variables' **다음에** 실행 합니다. `install.sh` 가 자동으로 실행 하므로,
> 보통은 따로 실행할 일이 없습니다.

```bash
./token.sh                  # 없거나 무효일 때만 발급 (여러 번 실행해도 안전)
./token.sh --account keep   # Keep argocd provider 의 keep 계정
./token.sh --rotate         # 토큰만 새로 발급. 이전 토큰은 즉시 무효
```

`--account keep` 은 `/k8s/common/argocd-keep-tokens` 와 `/k8s/common/keep/argocd-api-token` 을 만듭니다.
`charts/argo-cd` 의 ExternalSecret 은 두 계정의 토큰 목록을 모두 읽으므로 `install.sh` 가 둘 다 실행합니다.

`token.sh` 가 만드는 파라미터는 세 개 입니다.

| 파라미터 | 읽는 곳 |
|---|---|
| `/k8s/common/argocd-server-secret` | argocd-secret 의 `server.secretkey` — **없을 때만** 만듭니다 (32 bytes, hex) |
| `/k8s/common/argocd-mcp-tokens` | argocd-secret 의 `accounts.mcp.tokens` — `install/eks/values.yaml` 과 `charts/argo-cd` 의 ExternalSecret 양쪽 |
| `/k8s/common/mcp-argocd/argocd-api-token` | mcp-argocd 파드의 `ARGOCD_API_TOKEN` (argocd-env-apps) |

Argo CD 는 API 토큰을 자기 `server.secretkey` 로 서명 하고, `jti` 가 계정의 토큰
목록에 있는지까지 봅니다. 그 키와 목록을 함께 SSM 에 고정해 두면 클러스터를 다시
만들어도 **같은 토큰이 그대로 통하므로, 재설치에 토큰 발급 절차가 붙지 않습니다.**
`argocd account generate-token` 은 목록을 클러스터 안에만 남기기 때문에 쓰지 않습니다.

SSM의 `ParameterNotFound`만 미생성 상태로 처리한다. 접근 거부·통신 오류·빈 응답은
서명 키나 토큰을 쓰기 전에 중단한다. 새 서명 키는 덮어쓰기 없이 생성하므로,
다른 설치 작업이 먼저 만든 키도 보존한다.

> **`argocd-server-secret` 은 이미 있으면 건드리지 않습니다.** 바꾸면 발급된 토큰과
> 로그인 세션이 모두 무효가 되기 때문입니다. 위 'Set variables' 를 돌렸다면 거기서
> 이미 만들어져 있고, 이 스크립트는 그대로 읽어 씁니다. 새 계정이라 건너뛰었다면
> 여기서 만들어 집니다 — 다만 같은 블록이 그 값으로 넣는
> `argo-workflows-client-secret`·`oauth2-proxy-client-secret`·`cookie-secret` 은
> 별개이므로 'Set variables' 를 마저 실행 해야 합니다.
>
> 반대로 'Set variables' 를 **나중에 다시** 돌리면 `argocd-server-secret` 이 새 값으로
> 덮이면서 mcp 토큰이 무효가 됩니다. 그때는 `./token.sh` 를 한 번 더 실행 하면
> 자동으로 다시 발급 됩니다.

## Install Argo CD and register addons

Python 3와 PyYAML이 필요하다. `install/eks/`에서 다음 명령으로 실행 의존성을 설치한다.

```bash
python3 -m pip install -r ../../requirements/runtime.txt
```

`./install.sh`는 다음을 차례로 실행한다. 한 단계라도 실패하면 그 단계 이름과 종료 코드를 출력하고 멈춘다.

1. `token.sh`: Argo CD 서명 키와 mcp 계정 토큰을 SSM에서 확인하거나 만든다.
2. `secrets.sh`: addon이 읽는 무작위 값을 없을 때만 SSM에 만든다(아래 'Addon secrets').
3. `build.sh`: SSM 값으로 `values.output.yaml`(0600)을 만든다. 값 조회가 하나라도 실패하면 기존 파일을 유지한다.
4. `helm upgrade --install argocd`: Argo CD를 설치하고 준비될 때까지 기다린다(`HELM_TIMEOUT`, 기본 10m).
5. `bootstrap.yaml`: 이 클러스터를 이름 `eks-demo`로 등록하는 cluster Secret과 `addons`·`apps` AppProject를 적용한다.
6. `addons-eks.yaml`과 `argocd-env-apps`의 `apps-eks.yaml`을 등록한다.

설치는 공개 DNS·로그인·`argocd` CLI를 사용하지 않는다. 부트스트랩 values는 Ingress를 만들지 않는다.
Argo CD UI(`https://<argocd-hostname>`)는 `istio`와 `argo-cd` addon이 동기화된 뒤 공용 ALB와
istio HTTPRoute로 응답한다. 도메인은 `terraform-env-demo`의 `3-alb`(`*.demo.opsp.dev`)가 소유한다.
`argo-cd` addon은 자동 sync다. `addons-eks.yaml`이 동기화되면 Argo CD가 자기 chart를 따로 sync한다.

```bash
./install.sh
```

addons가 동기화되어 `kanidm` Pod가 준비되면 `kanidm.sh`를 한 번 실행한다(아래 'Kanidm').

## Addon secrets

`./secrets.sh`는 addon이 읽는 무작위 값(OIDC client secret, DB·관리자 비밀번호, 암호화 키, Kanidm 내부 TLS)을
SSM에 만든다. **없는 파라미터만 만들고 있는 값은 바꾸지 않는다.** DB 비밀번호나 암호화 키를 바꾸면 기존 데이터를 읽을 수 없기 때문이다.
`install.sh`가 Argo CD 설치 전에 실행한다. `argocd-secret`이 OIDC client secret을 읽으므로 하나라도 없으면 Argo CD가 시작하지 않는다.

```bash
./secrets.sh           # 없는 값만 만든다
./secrets.sh --check   # 만들지 않고 없는 값만 출력한다. 하나라도 없으면 종료 코드 1
```

- 값은 출력하지 않는다. `ParameterNotFound`만 미생성으로 처리하고, 권한·통신 오류는 쓰기 전에 중단한다.
- Kanidm 내부 CA를 새로 만들면 CA 인증서를 출력한다. `charts/kanidm/values-template.yaml.j2`의 `ca.crt`를 그 값으로 바꾼다.
- 사람이 정하는 값(GitHub OAuth App, Slack bot token 등)은 'Set variables'와 각 chart README를 따른다.

## Kanidm

Kanidm(`charts/kanidm`)은 관리자 비밀번호와 OAuth2 client secret을 직접 만든다. 정해 둔 값을 넣는 방법이 없다.
`./kanidm.sh`는 SSM 값이 Kanidm에서 통하는지 확인하고, 없거나 통하지 않을 때만 Kanidm이 만든 값으로 SSM을 바꾼다.

| 파라미터 | 확인 | 다를 때 |
| --- | --- | --- |
| `/k8s/common/kanidm/idm-admin-password` | 이 값으로 `idm_admin` 로그인 | `kanidmd recover-account idm_admin`의 새 비밀번호를 저장하고 `kanidm-idm-admin` Secret을 갱신 |
| `/k8s/common/kanidm/dex-client-secret` | `kanidm system oauth2 show-basic-secret dex`와 비교 | 저장하고 `argocd-secret`을 갱신한 뒤 Dex를 재시작 |

```bash
./kanidm.sh                                # 현재 kubectl context
KUBE_CONTEXT=eks-demo ./kanidm.sh          # context 지정
```

- 비밀번호는 Pod spec이 아니라 표준 입력으로 일회용 `kanidm/tools` Pod에 넘긴다. 값은 출력하지 않는다.
- OAuth2 client `dex`가 없으면 멈춘다. Argo CD에서 `kanidm`을 sync해 provisioning Job을 먼저 실행한다.

## Delete

### Delete eks cluster

```bash
terraform destroy
```
