# nexus

Nexus Repository Community Edition을 공식 이미지 `sonatype/nexus3`로 배포한다. 관리 클러스터(`eks-demo`)에만
배포하며 namespace는 `addon-nexus`, 주소는 `https://nexus.demo.opsp.dev`이다.

Sonatype의 현재 chart(`nxrm-ha`)는 Pro 라이선스가 필요하고, Community Edition용 chart(`nexus-repository-manager`)는
3.64에서 보관됐다. 그래서 `opspresso/helm-charts`의 `app` chart로 배포한다.

## 구성

- Deployment `nexus` 1개(`Recreate`), gp3 PVC 50Gi(`/nexus-data`). heap 1Gi, direct memory 1Gi, 메모리 한도 3Gi.
- HTTPRoute `nexus`가 `/` 전체를 `nexus:8081`로 보낸다.
- NetworkPolicy가 gateway(`istio-system`)와 같은 namespace의 Pod만 8081에 접속하게 한다.

## 로그인

모든 Dex client와 같은 규칙을 따른다(`env/<cluster>.yaml`의 `sso`).

- UI와 API(`/repository/` 밖)는 oauth2-proxy(Dex)로 로그인한 사용자만 연다.
  gateway가 `X-Auth-Request-Preferred-Username`(GitHub login)을 붙이고, Nexus는 Remote User Token realm으로 그 사용자를 로그인시킨다.
- `nexus.admins`(`sre` 팀의 GitHub login)는 `nx-admin`이다. Community Edition은 group을 역할에 연결할 수 없어 목록을 코드에 둔다.
  `sre` 팀 구성원이 바뀌면 이 목록도 고친다. 목록에 없는 사용자는 익명 읽기 권한만 갖는다.
- `/repository/`(Maven, npm 등 패키지 클라이언트)는 oauth2-proxy를 거치지 않는다. 익명 읽기 또는 Nexus 사용자 토큰·비밀번호를 쓴다.
  이 경로에서는 gateway가 사용자 header를 지워 위조할 수 없다.
- 로컬 `admin`(`/k8s/common/nexus/admin-password`)은 API와 동기화 Job만 쓴다.

CronJob `nexus-sync`가 10분마다 다음을 맞춘다. 실패하면 이후 단계를 하지 않는다.

1. 처음 실행할 때 `/nexus-data/admin.password`로 로그인해 admin 비밀번호를 SSM 값으로 바꾼다.
2. Community Edition EULA를 수락한다.
3. Remote User Token capability(header `X-Auth-Request-Preferred-Username`)를 Groovy script로 만들거나 고친다.
   REST API에 capability endpoint가 없어서 `-Dnexus.scripts.allowCreation=true`를 켠다.
4. 활성 realm을 `rutauth-realm`, `NexusAuthenticatingRealm`으로, 익명 읽기를 켠다.
5. `nexus.admins` 사용자를 만들고 `nx-admin`을 준다. 그 밖의 로컬 사용자(admin·anonymous 제외)는 `nx-anonymous`로 맞춘다.

```bash
kubectl -n addon-nexus create job --from=cronjob/nexus-sync nexus-sync-manual
kubectl -n addon-nexus logs -f job/nexus-sync-manual
```

## SSM 파라미터

| 파라미터 | 용도 |
| --- | --- |
| `/k8s/common/nexus/admin-password` | 로컬 `admin` 비밀번호. 동기화 Job이 첫 실행 때 설정한다 |
