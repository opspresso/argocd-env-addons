# lldap

아이디·비밀번호로 addon에 로그인하게 하는 경량 LDAP 디렉터리다. Argo CD Dex의 connector `lldap`이
LDAP으로 사용자를 확인하고, LLDAP 그룹 이름을 claim `groups`로 넘긴다.
namespace는 `addon-lldap`, 웹 UI 주소는 `https://id.demo.opsp.dev`다.

공식 이미지 `lldap/lldap`(rootless)을 opspresso `app` chart로 배포한다. LLDAP은 Helm chart를 내지 않는다.

## 로그인 흐름

1. addon(Grafana, Keep, GitLab 등)이 Argo CD Dex로 보낸다.
2. Dex의 LLDAP 로그인 폼에 LLDAP 아이디·비밀번호를 넣는다. connector가 `lldap` 하나라 선택 화면은 없다.
3. Dex는 `uid=<admin>,ou=people,<base_dn>`으로 bind해 사용자와 그룹을 찾는다.
4. 그룹 `sre`는 관리자, `dev`는 일반 사용자다(`env/<cluster>.yaml`의 `sso`). 그룹이 없는 LLDAP 사용자도
   로그인할 수 있으며 읽기 권한만 받는다. Keep만 그룹이 없는 사용자를 거부한다.

## 관리자 계정

LLDAP 관리자는 Argo CD 관리자와 같은 값을 쓴다.

| 파라미터 | 용도 |
| --- | --- |
| `/k8s/common/admin-user` | LLDAP 관리자 아이디, Dex bind 사용자 |
| `/k8s/common/admin-password` | LLDAP 관리자 비밀번호, Dex bind 비밀번호 |
| `/k8s/common/lldap/jwt-secret` | 웹 UI 세션 서명 키. 바꾸면 모든 세션이 끊긴다 |
| `/k8s/common/lldap/key-seed` | 비밀번호 저장 키의 seed. **바꾸면 모든 사용자 비밀번호가 맞지 않는다** |

- `lldap/*` 값은 `install/eks/secrets.sh`가 없을 때만 만든다.
- LLDAP은 시작할 때마다 관리자 비밀번호를 SSM 값으로 되돌린다(`LLDAP_FORCE_LDAP_USER_PASS_RESET=always`).
  웹 UI에서 관리자 비밀번호를 바꾸지 말고 SSM 값을 바꾼다.
- SSM 값을 바꾼 뒤에는 ExternalSecret `lldap-secret`(addon-lldap)과 `argocd-dex-lldap`(argocd)이 새 값을 읽은 다음
  `lldap` Deployment와 `argocd-dex-server`를 재시작한다.

## 그룹과 사용자

- PostSync Job `lldap-bootstrap`이 sync마다 `lldap.admin_groups`·`lldap.member_groups`(`sre`, `dev`)를 만들고
  관리자를 `lldap_admin`과 `sre`에 넣는다. 아무것도 지우지 않는다.
- 사용자 추가·그룹 배정·비밀번호 재설정은 웹 UI에서 관리자로 한다. 사용자는 자기 비밀번호를 웹 UI에서 바꾼다.
- Dex는 email이 없는 사용자의 로그인을 거부한다. 사용자를 만들 때 email을 넣는다.
- SMTP가 없어 비밀번호 재설정 메일은 보내지 않는다.
- GitLab CE 관리자는 그룹이 아니라 `gitlab.admins`의 로그인 이름으로 정한다.
  GitLab은 `admin`을 예약해 LLDAP 관리자를 `admin1`로 만든다. `sre`에 사용자를 넣으면 이 목록에도 추가한다.
- Grafana 로컬 관리자도 로그인 이름이 `admin`이다. LLDAP 관리자는 email로 이 계정에 연결된다. 두 email이 다르면
  Grafana 로그인이 `unable to create user`로 실패한다. Grafana가 이미 있으면 관리자 email을 `lldap.admin_email`로 바꾼다.

  ```bash
  kubectl -n addon-grafana exec deploy/grafana -c grafana -- sh -c \
    'curl -s -u "$GF_SECURITY_ADMIN_USER:$GF_SECURITY_ADMIN_PASSWORD" -X PUT -H "Content-Type: application/json" \
     -d "{\"email\":\"admin@demo.opsp.dev\",\"login\":\"admin\"}" http://localhost:3000/api/users/1'
  ```

## 저장소와 백업

- SQLite `/data/users.db`와 `/data/lldap_config.toml`이 PVC `lldap`(gp3 1Gi)에 있다. 설정은 환경 변수가 덮어쓴다.
- `lldap.base_dn`은 처음 시작한 뒤 바꾸지 않는다. 모든 DN이 바뀐다.
- 별도 백업은 없다. PVC를 잃으면 bootstrap이 그룹과 관리자를 다시 만들지만 다른 사용자는 다시 만들어야 한다.

## 네트워크

NetworkPolicy는 웹 UI(17170)를 `istio-system`과 같은 namespace에, LDAP(3890)을 `argocd-dex-server`에만 연다.
LDAP은 클러스터 안에서 TLS 없이 쓴다.
