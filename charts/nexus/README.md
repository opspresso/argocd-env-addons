# nexus

Nexus Repository Community Edition을 공식 이미지 `sonatype/nexus3`로 배포한다. 관리 클러스터(`eks-demo`)에만
배포하며 namespace는 `addon-nexus`, 주소는 `https://nexus.demo.opsp.dev`이다.

Sonatype의 현재 chart(`nxrm-ha`)는 Pro 라이선스가 필요하고, Community Edition용 chart(`nexus-repository-manager`)는
3.64에서 보관됐다. 그래서 `opspresso/helm-charts`의 `app` chart로 배포한다.

## 구성

- Deployment `nexus` 1개(`Recreate`), gp3 PVC 50Gi(`/nexus-data`). heap 1Gi, direct memory 1Gi, 메모리 한도 3Gi.
- HTTPRoute `nexus`가 `/` 전체를 `nexus:8081`로 보낸다.
- NetworkPolicy가 gateway(`istio-system`)와 같은 namespace의 Pod만 8081에 접속하게 한다.
  LLDAP의 NetworkPolicy(`charts/lldap`)는 Nexus Pod의 LDAP(3890) 접속을 허용한다.

## 로그인

모든 addon과 같은 LLDAP 계정·그룹 규칙을 따른다(`env/<cluster>.yaml`의 `sso`). Community Edition은 OIDC를
지원하지 않으므로 화면 로그인은 oauth2-proxy(플랫폼 Dex)가, 사용자와 그룹은 LLDAP(LDAP 사용자 원천)이 맡는다.

| 경로 | 인증 | 권한 |
| --- | --- | --- |
| UI·API(`/repository/` 밖) | oauth2-proxy(Dex, LLDAP). `sso.admin_groups`만 통과한다 | gateway가 붙인 `X-Auth-Request-Preferred-Username`(LLDAP 아이디)로 Remote User Token realm이 로그인시킨다 |
| `/repository/`(Maven·npm 등 패키지 클라이언트) | LLDAP 아이디·비밀번호(HTTP basic) 또는 익명 | gateway가 사용자 header를 지운다. 위조할 수 없다 |

- LLDAP 그룹이 Nexus 역할이 된다. `sso.admin_groups`(`sre`)는 `nx-admin`, `sso.member_groups`(`dev`)는
  `nx-anonymous`(읽기)다. 그룹에 없는 사용자와 익명 사용자는 읽기만 한다.
- 사용자를 추가하거나 그룹을 바꾸려면 LLDAP 웹 UI(`charts/lldap/README.md`)에서 한다. Nexus에서 바꿀 것은 없다.
- 로컬 `admin`(`/k8s/common/nexus/admin-password`)은 비상용과 동기화 Job용이다. LLDAP 관리자의 아이디도 `admin`이라
  oauth2-proxy로 로그인한 LLDAP 관리자는 로컬 `admin`으로 들어간다.
- LDAP bind 사용자는 플랫폼 Dex와 같은 LLDAP 관리자(`/k8s/common/admin-user`, `admin-password`)다.

CronJob `nexus-sync`가 10분마다 다음을 맞춘다. 단계가 실패하면 Job이 실패하고 이후 단계를 하지 않는다.

1. 처음 실행할 때 `/nexus-data/admin.password`로 로그인해 admin 비밀번호를 SSM 값으로 바꾼다.
2. Community Edition EULA를 수락한다.
3. LDAP 서버 `lldap`을 만들거나 같은 설정으로 덮어쓴다(그룹을 역할로 사용, static group `member`).
4. 활성 realm을 `rutauth-realm`, `LdapRealm`, `NexusAuthenticatingRealm` 순서로, 익명 읽기를 켠다.
5. Rut Auth capability(header `X-Auth-Request-Preferred-Username`)를 만든다.
6. `sso` 그룹마다 같은 ID의 Nexus 역할을 만들어 `nx-admin` 또는 `nx-anonymous`를 준다.
7. LLDAP에 같은 아이디가 있는 로컬 사용자를 지운다. 로컬 사용자가 남으면 그 역할이 LLDAP 그룹 권한에 더해진다.

LLDAP에 없는 로컬 사용자(예: CI 배포 계정)는 지우지 않으며, 그 역할은 로컬 `admin`이 관리한다.

```bash
kubectl -n addon-nexus create job --from=cronjob/nexus-sync nexus-sync-manual
kubectl -n addon-nexus logs -f job/nexus-sync-manual
```

## SSM 파라미터

| 파라미터 | 용도 |
| --- | --- |
| `/k8s/common/nexus/admin-password` | 로컬 `admin` 비밀번호. 동기화 Job이 첫 실행 때 설정한다 |
| `/k8s/common/admin-user`, `/k8s/common/admin-password` | LDAP bind 사용자(LLDAP 관리자) |
