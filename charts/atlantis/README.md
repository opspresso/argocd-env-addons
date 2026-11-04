# atlantis

Terraform PR 자동화. 관리 클러스터(`eks-demo`)에만 배포하며 namespace는 `addon-atlantis`다.

- `https://atlantis.demo.opsp.dev`(UI)는 oauth2-proxy(Dex)로 로그인한 사용자(`sso` 그룹 구성원)만 연다.
- GitHub webhook은 `https://atlantis-public.demo.opsp.dev/events`로 받는다. 로그인 없이 열고 webhook secret으로 검증한다.
- 허용 저장소는 `github.com/opspresso/terraform-*`이다. GitHub 사용자는 `nalbam-bot`이다.
- Terraform은 EKS Pod Identity로 IAM 역할 `pod-role--atlantis`(AdministratorAccess)를 쓴다
  (terraform-env-demo `demo/4-role`, `demo/5-eks`).

## variables

```bash
# variables
export GITHUB_USER="nalbam-bot"

export GITHUB_TOKEN="REPLACE_ME"
export GITHUB_SECRET="REPLACE_ME"

# put aws ssm parameter store
aws ssm put-parameter --name /k8s/common/github/${GITHUB_USER}/token --value "${GITHUB_TOKEN}" --type SecureString --overwrite | jq .
aws ssm put-parameter --name /k8s/common/github/${GITHUB_USER}/secret --value "${GITHUB_SECRET}" --type SecureString --overwrite | jq .

# get aws ssm parameter store
export GITHUB_TOKEN=$(aws ssm get-parameter --name "/k8s/common/github/${GITHUB_USER}/token" --with-decryption | jq .Parameter.Value -r)
export GITHUB_SECRET=$(aws ssm get-parameter --name "/k8s/common/github/${GITHUB_USER}/secret" --with-decryption | jq .Parameter.Value -r)
```
