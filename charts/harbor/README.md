# harbor

공식 chart(`goharbor/harbor`)로 Harbor를 배포한다. 관리 클러스터(`eks-demo`)에만 배포하며 namespace는 `addon-harbor`,
주소는 `https://harbor.demo.opsp.dev`이다.

## 구성

- Harbor 2.15 이미지는 amd64 전용이다. 모든 Pod는 NodePool `harbor-amd64`(terraform-env-demo `demo/6-eks-node`)에서
  실행되며 taint `opspresso.com/harbor`를 허용한다. Harbor가 arm64 이미지(2.16 이상)를 내면 nodeSelector·toleration과 NodePool을 지운다.
- gateway가 TLS를 종료한다. HTTPRoute `harbor`가 chart의 nginx(`harbor:80`)로 보내고, nginx가 portal·API·registry(`/v2/`)를 나눈다.
- 저장소는 gp3 PVC다: registry 50Gi, database 5Gi, trivy 5Gi, redis·job log 1Gi. `resourcePolicy: keep`이라 Application을 지워도 PVC는 남는다.
- 내장 PostgreSQL·Valkey 비밀번호는 chart가 평문 값만 받으므로 기본값을 쓴다. NetworkPolicy `harbor-data`가 같은 namespace의 Pod만 접속하게 한다.

## 로그인

모든 Dex client와 같은 규칙을 따른다(`env/<cluster>.yaml`의 `argocd.github`).

- Argo CD Dex의 client `harbor-sso`로 GitHub 로그인한다. 첫 로그인에서 사용자가 만들어진다(`oidc_auto_onboard`).
- `opspresso:sre` 팀은 Harbor 관리자(`oidc_admin_group`), 그 밖의 사용자는 일반 사용자다.
- OIDC 설정은 ExternalSecret `harbor-oidc`의 `CONFIG_OVERWRITE_JSON`이며 core가 시작할 때마다 적용한다.
- 로컬 `admin`(`/k8s/common/harbor/admin-password`)은 OIDC 모드에서도 로그인 화면의 로컬 폼으로 쓸 수 있다. Harbor는 이 폼을 숨기는 설정이 없다.
- docker CLI는 비밀번호 대신 사용자 프로필의 **CLI secret**으로 로그인한다.

## SSM 파라미터

| 파라미터 | 용도 |
| --- | --- |
| `/k8s/common/harbor/admin-password` | 로컬 `admin`의 첫 비밀번호. 첫 시작 때만 읽는다 |
| `/k8s/common/harbor/secret-key` | 16자. 저장된 자격 증명을 암호화한다. 바꾸면 기존 값을 읽을 수 없다 |
| `/k8s/common/harbor/oidc-client-secret` | Dex client `harbor-sso`의 secret. Argo CD `argocd-secret`도 읽는다 |

Dex는 시작할 때만 client secret을 읽는다. secret을 바꾸면 `kubectl -n argocd rollout restart deploy/argocd-dex-server`를 실행한다.
