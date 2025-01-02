# grafana

## variables

```bash
# variables
export GITHUB_ORG="opspresso"

export ADMIN_USERNAME="admin"
export ADMIN_PASSWORD="REPLACE_ME"

export GRAFANA_GITHUB_ID="REPLACE_ME" # github OAuth Apps <https://github.com/organizations/opspresso/settings/applications>
export GRAFANA_GITHUB_SECRET="REPLACE_ME" # github OAuth Apps

# put aws ssm parameter store
aws ssm put-parameter --name /k8s/common/admin-user --value "${ADMIN_USERNAME}" --type SecureString --overwrite | jq .
aws ssm put-parameter --name /k8s/common/admin-password --value "${ADMIN_PASSWORD}" --type SecureString --overwrite | jq .

aws ssm put-parameter --name /k8s/${GITHUB_ORG}/grafana-github-id --value "${GRAFANA_GITHUB_ID}" --type SecureString --overwrite | jq .
aws ssm put-parameter --name /k8s/${GITHUB_ORG}/grafana-github-secret --value "${GRAFANA_GITHUB_SECRET}" --type SecureString --overwrite | jq .

# get aws ssm parameter store
export ADMIN_USERNAME=$(aws ssm get-parameter --name /k8s/common/admin-user --with-decryption | jq .Parameter.Value -r)
export ADMIN_PASSWORD=$(aws ssm get-parameter --name /k8s/common/admin-password --with-decryption | jq .Parameter.Value -r)

export GRAFANA_GITHUB_ID=$(aws ssm get-parameter --name "/k8s/${GITHUB_ORG}/grafana-github-id" --with-decryption | jq .Parameter.Value -r)
export GRAFANA_GITHUB_ID=$(aws ssm get-parameter --name "/k8s/${GITHUB_ORG}/grafana-github-secret" --with-decryption | jq .Parameter.Value -r)
```
