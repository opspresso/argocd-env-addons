# gitlab

공식 GitLab chart(`gitlab/gitlab`)로 GitLab CE를 배포한다.
관리 클러스터(`eks-demo`)에만 배포하며 namespace는 `addon-gitlab`, 주소는 `https://gitlab.demo.opsp.dev`이다.

## 구성

GitLab 19(chart 10.x)는 PostgreSQL·Redis·MinIO를 더 이상 포함하지 않는다. 이 chart는 다음으로 채운다.

| 구성 요소 | 내용 |
| --- | --- |
| `gitlab-webservice-default` | Puma와 Workhorse. HTTPRoute `gitlab`이 `/` 전체를 Workhorse 포트 `8181`로 보낸다 |
| `gitlab-sidekiq-all-in-1-v2` | 백그라운드 작업 |
| `gitlab-gitaly` | Git 저장소. gp3 PVC 50Gi |
| `gitlab-toolbox` | `gitlab-rails console`, `backup-utility` |
| `gitlab-migrations-*` | DB migration Job. 설정이 바뀔 때마다 새로 실행된다 |
| `gitlab-postgres` | PostgreSQL 18(`opspresso/helm-charts` `postgres`). gp3 PVC 20Gi. 사용자 `gitlab`은 superuser라 migration이 필요한 extension을 만든다 |
| `gitlab-valkey` | Valkey(`opspresso/helm-charts` `valkey`). `maxmemory` 512MB, 가득 차면 쓰기를 거부한다(`noeviction`) |
| S3 | `opspresso-gitlab-{artifacts,lfs,uploads,packages,backups,tmp}`(terraform-env-apps `demo/8-gitlab`) |

- 끈 구성 요소: gitlab-shell(SSH), KAS, registry, pages, exporter, 내장 nginx·cert-manager·Prometheus·Runner·Envoy Gateway.
  gateway가 SSH를 라우팅하지 않으므로 Git은 HTTPS로 clone·push한다.
- 모든 GitLab Pod는 ServiceAccount `gitlab`을 쓴다. EKS Pod Identity가 이 계정에 IAM 역할 `pod-role--gitlab`을 붙인다
  (terraform-env-demo `demo/4-role`, `demo/5-eks`). S3 연결 Secret `gitlab-object-storage`에는 키가 없고 `use_iam_profile: true`만 있다.
- webservice·sidekiq는 HPA를 만들지만 `minReplicas`·`maxReplicas`를 1로 고정한다.

### 보존해야 하는 데이터

- `gitlab-rails-secret` 등 chart의 `shared-secrets` Job이 처음 설치할 때 만든 Secret. DB에 암호화해 둔 값(CI 변수, 토큰, 2FA)의 키다.
  잃으면 그 값을 읽을 수 없다. namespace를 지우기 전에 백업한다.
- PostgreSQL·Gitaly·Valkey PVC. `postgres`·`valkey` StatefulSet은 Application을 지우면 PVC도 지운다.
  gp3는 `Retain`이므로 EBS 볼륨은 남는다.

## SSM 파라미터

`install/eks/secrets.sh`가 없을 때만 만든다. 값이 없으면 ExternalSecret이 실패하고 Pod가 시작하지 않는다.

| 파라미터 | 용도 |
| --- | --- |
| `/k8s/common/gitlab/root-password` | `root`의 첫 비밀번호. GitLab은 처음 설치할 때만 읽는다 |
| `/k8s/common/gitlab/postgres-password` | PostgreSQL 사용자 `gitlab`. PostgreSQL은 데이터 디렉터리를 처음 만들 때만 읽는다 |
| `/k8s/common/gitlab/valkey-password` | Valkey `requirepass` |
| `/k8s/common/gitlab/oidc-client-secret` | Dex client `gitlab-sso`의 secret. Argo CD `argocd-secret`도 읽으므로, 없으면 `argocd-secret` 전체가 갱신되지 않는다 |

`root-password`와 `postgres-password`는 첫 설치 뒤에 바꿔도 반영되지 않는다. PostgreSQL 비밀번호를 바꾸려면 DB에서
`ALTER USER`를 먼저 실행하고 SSM을 같은 값으로 바꾼다.

## 로그인

모든 Dex client와 같은 규칙을 따른다(`env/<cluster>.yaml`의 `sso`).

- LLDAP 사용자는 Argo CD Dex(`https://argocd.demo.opsp.dev/api/dex`)를 거쳐 로그인한다.
  첫 로그인에서 관리자 승인 없이 사용자가 만들어진다. provider 설정은 ExternalSecret `gitlab-oidc-provider`가 만든다.
- `gitlab.admins`(`sso.admin_groups` 구성원의 login 이름)는 관리자, 다른 사용자는 일반 사용자다.
- 로그인 화면은 바로 Dex로 이동한다(`autoSignInWithProvider`). 가입과 웹 비밀번호 로그인은 꺼져 있다.
- `root`(`/k8s/common/gitlab/root-password`)는 API·rails console에서만 쓴다.

GitLab CE는 OIDC group으로 관리자를 지정할 수 없다(Premium 이상). 그래서 관리자 login 목록을
`env/<cluster>.yaml`의 `gitlab.admins`에 둔다. LLDAP `sre` 그룹 구성원이 바뀌면 이 목록도 함께 고친다.
GitLab은 `admin`을 예약하므로 LLDAP `admin`은 `admin1`이다.
CronJob `gitlab-admin-sync`가 10분마다 toolbox Pod에서 `gitlab-rails runner`를 실행한다.

- SSO 사용자 중 목록에 있는 사용자는 관리자로, 그 밖의 사용자는 일반 사용자로 맞춘다. `root`는 바꾸지 않는다.
- 가입과 웹 비밀번호 로그인이 켜져 있으면 끈다. 이 두 설정은 DB에 저장되며 chart 값으로 바꿀 수 없다.
- 목록이 비어 있으면 아무것도 바꾸지 않고 실패한다.
- 처음 로그인한 사용자는 다음 실행 때 관리자가 된다. 바로 적용하려면 Job을 만든다.

```bash
kubectl -n addon-gitlab create job --from=cronjob/gitlab-admin-sync gitlab-admin-sync-manual
kubectl -n addon-gitlab logs -f job/gitlab-admin-sync-manual
```

Dex는 시작할 때만 client secret을 읽는다. `/k8s/common/gitlab/oidc-client-secret`을 바꾸면 `argocd-secret`이 갱신된 뒤
`kubectl -n argocd rollout restart deploy/argocd-dex-server`를 실행한다. 재시작하지 않으면 GitLab 로그인이
`Invalid client credentials`로 실패한다.

## 백업

`backup-utility`는 IAM 역할로 S3에 쓰므로 `--s3tool awscli`를 붙인다. 백업 CronJob은 켜지 않았다.

```bash
kubectl -n addon-gitlab exec deploy/gitlab-toolbox -- backup-utility --s3tool awscli
```
