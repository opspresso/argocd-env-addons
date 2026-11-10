# atlantis

> 배포하지 않는다. ApplicationSet은 `backup/atlantis.yaml`에 보관한다. 되살리려면 `addons/eks/`로 옮긴다.

Terraform PR 자동화. 관리 클러스터(`eks-demo`)에만 배포하며 namespace는 `addon-atlantis`다.

- `https://atlantis.demo.opsp.dev`(UI)는 oauth2-proxy(Dex)로 로그인한 사용자만 연다.
- GitHub webhook은 `https://atlantis-public.demo.opsp.dev/events`로 받는다. 로그인 없이 열고 webhook secret으로 검증한다.
- 허용 저장소는 `github.com/opspresso/terraform-*`이다. GitHub 사용자는 `nalbam-bot`이다.
- Terraform은 EKS Pod Identity로 IAM 역할 `pod-role--atlantis`(AdministratorAccess)를 쓴다
  (terraform-env-demo `demo/4-role`, `demo/5-eks`).

## SSM 파라미터

`nalbam-bot`의 GitHub token과 webhook secret은 밖에서 발급하는 값이라 설치가 만들지 않는다. 되살리기 전에 넣는다.

| 파라미터 | 용도 |
| --- | --- |
| `/k8s/common/github/nalbam-bot/token` | GitHub API token |
| `/k8s/common/github/nalbam-bot/secret` | GitHub webhook secret |

```bash
aws ssm put-parameter --name /k8s/common/github/nalbam-bot/token --value "<token>" --type SecureString
aws ssm put-parameter --name /k8s/common/github/nalbam-bot/secret --value "<secret>" --type SecureString
```
