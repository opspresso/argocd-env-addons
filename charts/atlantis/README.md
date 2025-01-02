# grafana

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
