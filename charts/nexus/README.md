# nexus

Nexus Repository Community Edition을 공식 이미지 `sonatype/nexus3`로 배포한다. 관리 클러스터(`eks-demo`)에만
배포하며 namespace는 `addon-nexus`, 주소는 `https://nexus.demo.opsp.dev`이다.

Sonatype의 현재 chart(`nxrm-ha`)는 Pro 라이선스가 필요하고, Community Edition용 chart(`nexus-repository-manager`)는
3.64에서 보관됐다. 그래서 `opspresso/helm-charts`의 `app` chart로 배포한다.

## 구성

- Deployment `nexus` 1개(`Recreate`), gp3 PVC 50Gi(`/nexus-data`). heap 1Gi, direct memory 1Gi, 메모리 한도 3Gi.
- HTTPRoute `nexus`(app chart `routing.httpRoute.rules`)가 `/` 전체를 `nexus:8081`로 보낸다. 클라이언트 경로 규칙은
  사용자 header를 지운다(아래 [로그인](#로그인)).
- NetworkPolicy가 gateway(`istio-system`)와 같은 namespace의 Pod만 8081에 접속하게 한다.
  LLDAP의 NetworkPolicy(`charts/lldap`)는 Nexus Pod의 LDAP(3890) 접속을 허용한다.

## 로그인

모든 addon과 같은 LLDAP 계정·그룹 규칙을 따른다(`env/<cluster>.yaml`의 `sso`). Community Edition은 OIDC를
지원하지 않으므로 화면 로그인은 oauth2-proxy(플랫폼 Dex)가, 사용자와 그룹은 LLDAP(LDAP 사용자 원천)이 맡는다.

| 경로 | 인증 | 권한 |
| --- | --- | --- |
| UI·관리 API(아래 클라이언트 경로 밖) | oauth2-proxy(Dex, LLDAP). `sso.admin_groups`만 통과한다 | gateway가 붙인 `X-Auth-Request-Preferred-Username`(LLDAP 아이디)로 Remote User Token realm이 로그인시킨다 |
| `/repository/`(Maven·npm 등 패키지 클라이언트) | LLDAP 아이디·비밀번호(HTTP basic) 또는 익명 | gateway가 사용자 header를 지운다. 위조할 수 없다 |
| `/service/rest/v1/assets`와 하위 경로 | Nexus 계정 인증 | 사용자 헤더를 제거하고 자산별 읽기·삭제 권한을 검사한다. 보안·설정 관리 API는 계속 SSO로 보호한다 |
| `/v2`·`/v2/` 하위(Docker 클라이언트) | Nexus Docker Bearer Token | gateway가 사용자 header를 지운다. Nexus 저장소 권한으로 push·pull을 검사한다 |

- LLDAP 그룹이 Nexus 역할이 된다. `sso.admin_groups`(`sre`)는 `nx-admin`, `sso.member_groups`(`dev`)는
  `nexus.delivery`가 꺼져 있으면 `nx-anonymous`(읽기)다. `nexus.delivery`가 켜지면 일반 그룹과 익명 사용자는 `nexus.publicRepositories`에 지정한
  패키지 저장소만 읽는다. Runway 산출물은 인증된 계정으로만 읽는다.
- 사용자를 추가하거나 그룹을 바꾸려면 LLDAP 웹 UI(`charts/lldap/README.md`)에서 한다. Nexus에서 바꿀 것은 없다.
- 로컬 `admin`(`/k8s/common/nexus/admin-password`)은 비상용과 동기화 Job용이다. LLDAP 관리자의 아이디도 `admin`이라
  oauth2-proxy로 로그인한 LLDAP 관리자는 로컬 `admin`으로 들어간다.
- LDAP bind 사용자는 플랫폼 Dex와 같은 LLDAP 관리자(`/k8s/common/admin-user`, `admin-password`)다.

CronJob `nexus-sync`가 10분마다 다음을 맞춘다. 단계가 실패하면 Job이 실패하고 이후 단계를 하지 않는다.

1. 처음 실행할 때 `/nexus-data/admin.password`로 로그인해 admin 비밀번호를 SSM 값으로 바꾼다.
2. Community Edition EULA를 수락한다.
3. LDAP 서버 `lldap`을 만들거나 같은 설정으로 덮어쓴다(그룹을 역할로 사용, static group `member`).
4. 활성 realm을 `rutauth-realm`, `LdapRealm`, `NexusAuthenticatingRealm`, `DockerToken` 순서로, 익명 읽기를 켠다.
5. Rut Auth capability(header `X-Auth-Request-Preferred-Username`)를 만든다.
6. `sso` 그룹마다 같은 ID의 Nexus 역할을 만든다. 관리자는 `nx-admin`이며, 일반 그룹은 delivery가 켜지면 `public-packages`, 아니면 `nx-anonymous`다.
7. LLDAP에 같은 아이디가 있는 로컬 사용자를 지운다. 로컬 사용자가 남으면 그 역할이 LLDAP 그룹 권한에 더해진다.

LLDAP에 없는 로컬 사용자(예: CI 배포 계정)는 지우지 않으며, 그 역할은 로컬 `admin`이 관리한다.

## Runway 산출물

`env/<cluster>.yaml`의 `nexus.delivery: true`는 `delivery.sh`로 다음 구성을 동기화한다.

| 저장소 | 용도 | 게시 정책 |
| --- | --- | --- |
| `runway-artifacts` | JAR·WAR 파일 | 같은 경로 덮어쓰기 금지 |
| `runway-images` | Docker 이미지, path-based routing | 같은 tag 덮어쓰기 금지, `latest` 예외 없음 |

Docker 주소는 `nexus.demo.opsp.dev/runway-images/<image>`다. 파일 주소는
`https://nexus.demo.opsp.dev/repository/runway-artifacts/<path>`다. 앱 산출물 저장소를 만들기 전에 익명 역할을
`public-packages`로 제한하므로 생성 직후에도 익명 읽기를 허용하지 않는다. 기존 공개 패키지는
`nexus.publicRepositories`에 이름을 명시한다. 목록 밖의 새 저장소를 자동 공개하지 않는다. 동기화가 만든 역할의 이름·설명·권한 형태가 정확히 일치하고 현재 그룹 목록에서 빠진 역할은 권한만 비운다. 수동 역할은 보존한다.

`runway-reader`는 두 저장소의 read·browse만, `runway-publisher`는 read·browse·add·edit만 가진다.
`runway-cleaner`는 두 저장소의 read·browse·delete만 가지며 게시 권한이 없다. 세 계정 모두 관리자 권한이 없고, 동기화는 각 계정의 역할을 정해진 역할 하나로 복원한다.
비밀번호는 SSM 값으로 최초 생성하며, 매 실행마다 기존 비밀번호를 바꾸지 않는다. 회전할 때는 운영자가
Nexus 계정과 SSM 값을 함께 갱신한다. 게시 자격 증명은 격리된 게시 단계에만 전달한다.
Runway의 삭제 어댑터는 cleaner 계정으로 해당 프로젝트 경로의 파일과 이미지 manifest만 삭제한다. 다른 프로젝트와 공유 blob은 보존하며, 실제 연동은 Runway 배포 버전에서 확인한다.

이 설정은 저장소와 계정을 준비한다. Runway 빌드·배포 연동 완료를 의미하지 않는다.

```bash
kubectl -n addon-nexus create job --from=cronjob/nexus-sync nexus-sync-manual
kubectl -n addon-nexus logs -f job/nexus-sync-manual
```

## SSM 파라미터

| 파라미터 | 용도 |
| --- | --- |
| `/k8s/common/nexus/admin-password` | 로컬 `admin` 비밀번호. 동기화 Job이 첫 실행 때 설정한다 |
| `/k8s/common/nexus/runway-publisher-password` | Runway 산출물 게시 계정의 최초 비밀번호 |
| `/k8s/common/nexus/runway-cleaner-password` | Runway 산출물 삭제 전용 계정의 최초 비밀번호 |
| `/k8s/common/nexus/runway-reader-password` | Runway 산출물 읽기 계정의 최초 비밀번호 |
| `/k8s/common/admin-user`, `/k8s/common/admin-password` | LDAP bind 사용자(LLDAP 관리자) |
