# gitlab-ce

GitLab CE를 Omnibus 이미지(`gitlab/gitlab-ce`) 하나로 실행한다.
관리 클러스터(`eks-demo`)에만 배포하며 주소는 `https://gitlab.demo.opsp.dev`이다.

## 구성

| 구성 요소 | 내용 |
| --- | --- |
| Deployment `gitlab-ce` | Puma·Sidekiq·Gitaly·PostgreSQL·Redis·nginx가 한 컨테이너에서 실행된다. replica 1, `Recreate` |
| PVC `gitlab-ce` | gp3 50Gi(`Retain`). `data/`는 `/var/opt/gitlab`, `config/`는 `/etc/gitlab`에 마운트한다 |
| HTTPRoute `gitlab-ce` | `istio-ingressgateway`에서 `/` 전체를 Service `gitlab-ce:80`으로 보낸다 |
| ExternalSecret `gitlab-ce-secret` | SSM 값 2개를 환경 변수로 넣는다 |

- 공식 GitLab chart(`gitlab/gitlab` 10.x)는 PostgreSQL·Redis·오브젝트 스토리지를 외부에 따로 둬야 한다. 이 chart는 그 대신 `opspresso/helm-charts`의 `app` chart로 Omnibus 이미지를 배포한다.
- 설정은 `values-template.yaml.j2`의 `GITLAB_OMNIBUS_CONFIG`(Ruby)에 있다. 컨테이너가 시작할 때마다 `gitlab-ctl reconfigure`가 읽으므로, 바꾼 설정은 Pod를 재시작해야 반영된다.
- gateway가 TLS를 종료하므로 nginx는 HTTP 80만 연다. SSH는 라우팅하지 않는다. Git은 HTTPS로 clone·push한다.
- 내장 Prometheus와 exporter는 끈다. 첫 시작은 DB migration 때문에 수 분 걸린다. `startupProbe`는 최대 15분 기다린다.
- `/etc/gitlab/gitlab-secrets.json`은 DB에 암호화해 저장한 값(CI 변수, 토큰, 2FA)의 키다. 잃으면 그 값을 읽을 수 없다. PVC를 지우지 않는다.

## SSM 파라미터

배포 전에 SecureString으로 등록한다. 값이 없으면 ExternalSecret이 실패하고 Pod가 시작하지 않는다.
`/k8s/common/gitlab-ce/oidc-client-secret`은 `charts/argo-cd`의 `argocd-secret`도 읽는다. 이 값이 없으면 `argocd-secret` 전체가 갱신되지 않으므로, 이 chart와 argo-cd 변경을 merge하기 전에 등록한다.

| 파라미터 | 용도 |
| --- | --- |
| `/k8s/common/gitlab-ce/root-password` | `root` 계정의 첫 비밀번호(`GITLAB_ROOT_PASSWORD`). DB를 처음 만들 때만 쓴다 |
| `/k8s/common/gitlab-ce/oidc-client-secret` | Dex client `gitlab-sso`의 secret. GitLab과 Argo CD Dex가 같은 값을 쓴다 |

```bash
for name in root-password oidc-client-secret; do
  aws ssm put-parameter --region ap-northeast-2 --type SecureString \
    --name "/k8s/common/gitlab-ce/${name}" \
    --value "$(openssl rand -base64 33 | tr -d '/+=' | cut -c1-32)"
done
```

`root-password`는 첫 시작 뒤에 바꿔도 반영되지 않는다. root 비밀번호는 GitLab UI 또는 `gitlab-rake "gitlab:password:reset[root]"`로 바꾼다.

## 로그인

- **GitHub**: Argo CD Dex(`https://argocd.demo.opsp.dev/api/dex`)를 거친다. Dex는 `opspresso` 조직 구성원만 받으므로, 첫 로그인에서 관리자 승인 없이 사용자가 만들어진다. 같은 이메일의 기존 사용자에게는 연결된다.
- **root**: `/k8s/common/gitlab-ce/root-password`의 값으로 로그인한다. GitLab CE는 OIDC group으로 관리자를 지정할 수 없으므로, 관리자 권한은 root가 Admin 영역에서 준다.

설치 직후 root로 로그인해 **Admin > Settings > General > Sign-up restrictions**에서 **Sign-up enabled**를 끈다. 이 설정은 DB에 저장되며 `gitlab.rb`로 바꿀 수 없다. 켜 두면 누구나 이메일로 가입을 신청할 수 있다.
