# jenkins

> 배포하지 않는다. ApplicationSet은 `backup/jenkins.yaml`에 보관한다. 되살리려면 `addons/eks/`로 옮긴다.

공식 chart(`jenkinsci/jenkins`)로 Jenkins를 배포한다. 관리 클러스터(`eks-demo`)에만 배포하며 namespace는 `addon-jenkins`,
주소는 `https://jenkins.demo.opsp.dev`이다.

## 로그인

모든 Dex client와 같은 규칙을 따른다(`env/<cluster>.yaml`의 `sso`).

- 플랫폼 Dex(`charts/dex`)의 client `jenkins-sso`로 로그인한다(`oic-auth` plugin). 로컬 사용자와 비밀번호 폼은 없다.
- `sso.admin_groups`는 `Overall/Administer`, 그 밖의 사용자는 읽기(`Overall/Read`, `Job/Read`, `View/Read`)만 한다.
- 보안 설정은 JCasC(`values-template.yaml.j2`)에 있다. UI에서 바꾼 보안 설정은 JCasC가 다시 적용될 때 덮어써진다.

## SSM 파라미터

| 파라미터 | 용도 |
| --- | --- |
| `/k8s/common/jenkins/oidc-client-secret` | Dex client `jenkins-sso`의 secret. 플랫폼 Dex의 `dex-secret`도 읽는다 |

Dex는 시작할 때만 client secret을 읽는다. secret을 바꾸면 `kubectl -n addon-dex rollout restart deploy/dex`를 실행한다.

## 빌드 agent

Kubernetes plugin이 빌드마다 agent Pod를 `addon-jenkins`에 만든다(요청 500m·512Mi, 한도 1Gi).
