# kanidm

[Kanidm](https://kanidm.github.io/kanidm/stable/)은 사람·그룹·인증 수단(패스키, 비밀번호+TOTP)을 관리하는 IdP다.
관리 클러스터(`eks-demo`)에만 배포하며 namespace는 `addon-kanidm`, 주소는 `https://idm.demo.opsp.dev`이다.
Argo CD Dex가 Kanidm으로 로그인시키고, 모든 addon은 Dex를 쓴다.

Kanidm은 Helm chart를 내지 않는다. 이 chart는 공식 이미지 `kanidm/server`를 `opspresso/helm-charts`의 `app` chart로 배포한다.

## 구성

| 구성 요소 | 내용 |
| --- | --- |
| Deployment `kanidm` | replica 1, `Recreate`. 설정은 ConfigMap `kanidm-config`의 `server.toml` |
| PVC `kanidm` | gp3 10Gi. `/data`에 DB(`kanidm.db`)와 online backup(`/data/backups/`) |
| HTTPRoute `kanidm` | `idm.demo.opsp.dev` → `kanidm:8443` |
| Job `kanidm-provision` | Argo CD sync 후(PostSync) 그룹과 Dex의 OAuth2 client를 맞춘다 |

## 인증 흐름

```
사용자 → addon(Argo CD, Grafana, Keep, GitLab, Jenkins, Harbor, oauth2-proxy)
       → Argo CD Dex (connector kanidm)
       → Kanidm (OAuth2 client dex, 패스키 또는 비밀번호+TOTP)
```

- 로그인할 수 있는 사람은 `env/<cluster>.yaml`의 `kanidm.groups`(`sre`, `dev`) 구성원이다. 다른 사람은 Kanidm이 거부한다.
- Kanidm은 claim `groups`에 그룹 이름(`sre`, `dev`)을 보낸다(scope `groups_name`).
- 각 addon의 권한은 `sso.admin_groups`(관리자)와 `sso.member_groups`(일반·읽기)로 정한다.

## TLS

kanidmd는 HTTPS만 받는다. ALB가 브라우저 TLS를 종료하고, gateway가 kanidmd로 다시 암호화한다.

- 서버 인증서는 내부 CA가 발급했다(ECDSA P-256, 10년, SAN `kanidm.addon-kanidm.svc.cluster.local`).
- gateway는 DestinationRule `istio-system/kanidm`으로 이 CA를 검증한다. CA 인증서는 공개 정보이므로
  `values-template.yaml.j2`에 두고 Secret `istio-system/kanidm-ca`로 만든다. ClusterSecretStore가 `istio-system`을 허용하지 않기 때문이다.
- 갱신: CA 키(`/k8s/common/kanidm/ca-key`)로 새 서버 인증서를 발급해 `tls-chain`·`tls-key`를 바꾸고 Pod를 재시작한다.
  CA를 바꾸면 `values-template.yaml.j2`의 CA 인증서도 바꾼다.

| SSM 파라미터 | 내용 |
| --- | --- |
| `/k8s/common/kanidm/tls-chain` | 서버 인증서 + CA 인증서 |
| `/k8s/common/kanidm/tls-key` | 서버 키 |
| `/k8s/common/kanidm/ca-crt` | CA 인증서 원본. `values-template.yaml.j2`에도 같은 값이 있다 |
| `/k8s/common/kanidm/ca-key` | CA 키. 인증서 갱신에만 쓴다 |
| `/k8s/common/kanidm/idm-admin-password` | `idm_admin` 비밀번호. provisioning Job이 쓴다 |
| `/k8s/common/kanidm/dex-client-secret` | OAuth2 client `dex`의 secret. Argo CD `argocd-secret`이 읽는다 |

## 처음 설치 (bootstrap)

1. `install/eks/secrets.sh`(install.sh가 실행)가 내부 TLS를 SSM에 만든다.
2. ApplicationSet이 Kanidm을 띄운다. `idm-admin-password`가 아직 없으므로 첫 `kanidm-provision`은 실패한다.
3. `install/eks/kanidm.sh`를 실행한다. `idm_admin` 비밀번호를 만들어 SSM에 넣는다.
4. Argo CD에서 `kanidm`을 다시 sync한다. `kanidm-provision`이 그룹 `sre`·`dev`와 client `dex`를 만든다.
5. `install/eks/kanidm.sh`를 다시 실행한다. client `dex`의 secret을 SSM에 넣고 Dex를 재시작한다.

두 값이 이미 맞으면 `kanidm.sh`는 아무것도 바꾸지 않는다. Kanidm 데이터를 잃어 다시 설치했을 때도 같은 순서를 따른다.

## 팀원 관리

`idm_admin`으로 CLI(`kanidm`, 이미지 `kanidm/tools`)에 로그인해 관리한다.

```bash
export KANIDM_URL=https://idm.demo.opsp.dev
kanidm login -D idm_admin

# 사람 추가: login 이름은 GitLab·Nexus 관리자 목록과 같아야 한다.
kanidm person create alice "Alice Kim"
kanidm person update alice --mail alice@example.com
kanidm group add-members dev alice        # 관리자는 sre

# 첫 로그인 수단 등록 링크(패스키 또는 비밀번호+TOTP). 링크를 본인에게 전한다.
kanidm person credential create-reset-token alice

# 팀 이동·퇴사
kanidm group remove-members dev alice
kanidm person delete alice
```

- 그룹 구성원 변경은 다음 로그인부터 모든 addon에 적용된다.
- GitLab CE와 Nexus CE는 그룹으로 관리자를 정할 수 없다. `sre` 구성원이 바뀌면 `gitlab.admins`·`nexus.admins`도 고친다.

## 백업

kanidmd가 매일 03:00 KST에 `/data/backups/`로 online backup을 만들고 7개를 남긴다. 같은 볼륨에 있으므로 볼륨을 잃으면 함께 잃는다.
gp3는 `Retain`이라 PVC를 지워도 EBS 볼륨은 남는다.

```bash
# 복원: Pod를 멈춘 상태에서 실행한다.
kanidmd database restore -c /config/server.toml /data/backups/<file>
```

## 비상 접근

Kanidm이 멈추면 Dex 로그인이 모두 멈춘다. 각 addon의 로컬 관리자 계정을 쓴다:
Argo CD `admin`(`/k8s/common/argocd-password`), GitLab `root`, Harbor `admin`, Grafana `admin`, Nexus `admin`.
