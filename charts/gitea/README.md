# gitea

공식 Gitea chart(`gitea-charts/gitea`, <https://gitea.com/gitea/helm-gitea>)로 Gitea를 배포한다.
관리 클러스터(`eks-demo`)에만 배포하며 namespace는 `addon-gitea`, 주소는 `https://gitea.demo.opsp.dev`이다.

## 구성

| 구성 요소 | 내용 |
| --- | --- |
| `gitea` | Deployment 1개. rootless 이미지 `docker.gitea.com/gitea:<appVersion>-rootless` |
| `gitea-shared-storage` | gp3 PVC 20Gi. 저장소, LFS, 첨부 파일, LevelDB queue, `app.ini`를 둔다 |
| `gitea-postgres` | PostgreSQL 18(`opspresso/helm-charts` `postgres`). gp3 PVC 10Gi. 같은 namespace의 Pod만 접속한다 |
| HTTPRoute `gitea` | chart의 Gateway API route. `istio-system/istio-ingressgateway`에서 `/` 전체를 `gitea-http:3000`으로 보낸다 |

- upstream chart가 기본으로 켜는 Bitnami `postgresql-ha`·`valkey-cluster`는 끈다. 복제본이 하나라 Valkey 없이
  session은 DB, cache는 memory, queue는 PVC의 LevelDB를 쓴다.
- PVC가 ReadWriteOnce라 배포 전략은 `Recreate`다. 새 Pod는 이전 Pod가 끝난 뒤 시작하므로 배포 중 잠깐 접속이 끊긴다.
- SSH는 끈다(`DISABLE_SSH`, `START_SSH_SERVER: false`). gateway가 SSH를 라우팅하지 않으므로 Git은 HTTPS로 clone·push한다.
  chart는 Service `gitea-ssh`를 항상 만들지만 그 포트에서 듣는 프로세스는 없다.
- Git LFS 서버는 켠다(`LFS_START_SERVER`).

### 보존해야 하는 데이터

- PVC `gitea-shared-storage`: Git 저장소와 `/data/gitea/conf/app.ini`. Gitea가 첫 시작 때 `app.ini`에 만든
  `SECRET_KEY`·`INTERNAL_TOKEN`·JWT secret은 DB에 암호화해 둔 값(2FA, 토큰, 연결 계정)의 키다. 잃으면 그 값을 읽을 수 없다.
- PVC `data-gitea-postgres-0`: 사용자, 이슈, PR, 설정.
- `gitea-shared-storage`는 annotation `argocd.argoproj.io/sync-options: Delete=false`와 `helm.sh/resource-policy: keep`이 있어
  Application을 지워도 남는다. `postgres` StatefulSet의 PVC는 Application을 지우면 함께 지워진다. gp3는 `Retain`이므로
  두 경우 모두 EBS 볼륨은 남는다.

## SSM 파라미터

`install/eks/secrets.sh`가 없을 때만 만든다. 값이 없으면 ExternalSecret이 실패하고 Pod가 시작하지 않는다.

| 파라미터 | 용도 |
| --- | --- |
| `/k8s/common/gitea/admin-password` | 로컬 관리자 `gitea_admin`의 비밀번호. init container가 시작할 때마다 이 값으로 맞춘다 |
| `/k8s/common/gitea/postgres-password` | PostgreSQL 사용자 `gitea`. PostgreSQL은 데이터 디렉터리를 처음 만들 때만 읽는다 |
| `/k8s/common/gitea/oidc-client-secret` | Dex client `gitea-sso`의 secret. 플랫폼 Dex의 `dex-secret`도 읽으므로, 없으면 `dex-secret` 전체가 갱신되지 않는다 |

`postgres-password`는 첫 설치 뒤에 바꿔도 PostgreSQL에 반영되지 않는다. Gitea는 Pod가 시작할 때 Secret `gitea-secret`의 값을
`app.ini`에 쓴다. ExternalSecret은 1시간마다 갱신하므로, 그 전에 Pod를 다시 시작하면 이전 비밀번호로 DB 접속에 실패한다.

1. DB에서 `ALTER USER gitea PASSWORD '<새 값>'`을 실행한다.
2. SSM `/k8s/common/gitea/postgres-password`를 같은 값으로 바꾼다.
3. ExternalSecret을 바로 갱신하고, `gitea-secret`의 `resourceVersion`이 바뀐 것을 확인한 뒤 Pod를 다시 시작한다.

```bash
kubectl -n addon-gitea get secret gitea-secret -o jsonpath='{.metadata.resourceVersion}'
kubectl -n addon-gitea annotate externalsecret gitea-secret force-sync="$(date +%s)" --overwrite
kubectl -n addon-gitea get secret gitea-secret -o jsonpath='{.metadata.resourceVersion}'
kubectl -n addon-gitea rollout restart deploy/gitea
```

## 로그인

모든 Dex client와 같은 규칙을 따른다(`env/<cluster>.yaml`의 `sso`).

- LLDAP 사용자는 플랫폼 Dex(`https://sso.demo.opsp.dev`, `charts/dex`)를 거쳐 로그인한다. 인증 소스 이름은 `SSO`이고
  callback은 `https://gitea.demo.opsp.dev/user/oauth2/SSO/callback`이다.
- 첫 로그인에서 관리자 승인 없이 사용자가 만들어진다. 사용자 이름은 Dex claim `preferred_username`(LLDAP 사용자 ID)이다.
  Dex는 그룹과 관계없이 모든 LLDAP 사용자를 인증하므로, `sso` 그룹이 없는 사용자도 일반 사용자로 로그인한다(GitLab과 같다).
  같은 email의 Gitea 계정이 있으면 묻지 않고 연결한다(`ACCOUNT_LINKING: auto`).
- `sso.admin_groups`의 그룹 구성원은 관리자, 다른 사용자는 일반 사용자다. Gitea는 로그인할 때마다 claim `groups`로
  관리자 권한을 맞춘다. 그룹에서 뺀 사용자는 다음 로그인 때 관리자 권한을 잃는다.
  Gitea는 관리자 그룹을 하나만 지정할 수 있으므로 `sso.admin_groups`가 하나가 아니면 렌더가 실패한다.
- 로그인 화면은 바로 Dex로 이동한다. 비밀번호 폼·passkey·OpenID 2.0 로그인과 Gitea 자체 가입은 꺼져 있다.
- Git over HTTPS는 사용자의 access token(**Settings > Applications**)을 비밀번호로 쓴다. SSO 사용자에게는 비밀번호가 없다.
- 로컬 관리자 `gitea_admin`(`/k8s/common/gitea/admin-password`)은 비상용이다. 비밀번호 폼이 꺼져 있어 API(basic auth)와
  `gitea admin` CLI에서만 쓴다.

init container `configure-gitea`가 Pod가 시작할 때마다 인증 소스 `SSO`를 만들거나 chart 값으로 갱신한다.
chart 값(issuer, scope, 관리자 그룹)이 바뀌면 Pod annotation `checksum/oauth_0`이 바뀌어 Pod가 다시 시작한다.
Dex client secret(`/k8s/common/gitea/oidc-client-secret`)만 바꿨다면 Secret `gitea-oidc`와 `dex-secret`이 갱신된 뒤 두 서비스를
다시 시작한다. 재시작하지 않으면 로그인이 `Invalid client credentials`로 실패한다.

```bash
kubectl -n addon-dex rollout restart deploy/dex
kubectl -n addon-gitea rollout restart deploy/gitea
```

## 백업

백업 CronJob은 켜지 않았다. `gitea dump`는 저장소·DB·`app.ini`를 zip 하나로 만든다. Pod의 `/tmp`는 emptyDir이라
Pod가 다시 시작하면 사라진다. 만든 파일은 바로 내려받고 지운다.

`gitea dump`는 실행 중인 Gitea에서 저장소와 DB를 차례로 읽는다. 그 사이에 push·migration이 있으면 저장소와 DB가 서로 다른
시점을 담을 수 있다. Gitea 공식 문서는 일관된 백업을 위해 서버를 멈추라고 한다. 이 Deployment는 Argo CD가 `selfHeal`로
replica 1을 되돌리고 dump도 같은 Pod에서 실행하므로, 아래 명령은 사용자가 쓰지 않는 시간에 실행한다.

```bash
kubectl -n addon-gitea exec deploy/gitea -c gitea -- gitea dump --type zip --file /tmp/gitea-dump.zip
kubectl -n addon-gitea cp -c gitea "$(kubectl -n addon-gitea get pod -l app.kubernetes.io/name=gitea -o name | cut -d/ -f2)":/tmp/gitea-dump.zip ./gitea-dump.zip
kubectl -n addon-gitea exec deploy/gitea -c gitea -- rm /tmp/gitea-dump.zip
```
