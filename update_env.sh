#!/bin/bash

# Update env/*.yaml with current AWS data (vpcId, acm_arn, target_group).
# Values are looked up by convention:
#   vpcId                     : VPC tagged Name=vpc-{env}
#   argocd.acm_arn            : ACM cert whose domain == argocd.hostname
#   atlantis.acm_arn          : ACM cert whose domain == hostname.public
#   target_group.public_http  : target group named {env}-{istio.target_group}
#   target_group.internal_http: target group named {env}-in-{istio.target_group}
# Existing values are replaced in place, preserving file formatting.

set -euo pipefail

SHELL_DIR=$(dirname $0)

command -v yq >/dev/null || { echo "yq is required"; exit 1; }

CURRENT_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

update() {
  FILE=$1
  KEY=$2
  OLD=$3
  NEW=$4

  if [ -z "${NEW}" ] || [ "${NEW}" == "None" ] || [ "${NEW}" == "null" ]; then
    echo "  ${KEY}: not found in aws, skipped"
    return
  fi

  if [ -z "${OLD}" ] || [ "${OLD}" == "null" ]; then
    echo "  ${KEY}: not set in file, skipped"
    return
  fi

  if [ "${OLD}" == "${NEW}" ]; then
    echo "  ${KEY}: unchanged"
    return
  fi

  perl -pi -e "s|\Q${OLD}\E|${NEW}|" ${FILE}
  echo "  ${KEY}: ${OLD} -> ${NEW}"
}

for FILE in ${SHELL_DIR}/env/*.yaml; do
  echo
  echo "Processing.. ${FILE}"

  ENV=$(yq '.env' ${FILE})
  ACCOUNT_ID=$(yq '.aws_account_id' ${FILE})
  REGION=$(yq '.aws_region' ${FILE})

  if [ "${ACCOUNT_ID}" != "${CURRENT_ACCOUNT_ID}" ]; then
    echo "  skipped: aws_account_id ${ACCOUNT_ID} != current account ${CURRENT_ACCOUNT_ID}"
    continue
  fi

  # vpcId
  VPC_ID=$(aws ec2 describe-vpcs --region ${REGION} \
    --filters "Name=tag:Name,Values=vpc-${ENV}" \
    --query 'Vpcs[0].VpcId' --output text)
  update ${FILE} "vpcId" "$(yq '.vpcId // ""' ${FILE})" "${VPC_ID}"

  # acm_arn
  CERTS=$(aws acm list-certificates --region ${REGION} --certificate-statuses ISSUED \
    --query 'CertificateSummaryList[].[DomainName,CertificateArn]' --output text)

  ARGOCD_HOST=$(yq '.argocd.hostname // ""' ${FILE})
  if [ -n "${ARGOCD_HOST}" ]; then
    ARN=$(echo "${CERTS}" | awk -v d="${ARGOCD_HOST}" '$1==d {print $2; exit}')
    update ${FILE} "argocd.acm_arn" "$(yq '.argocd.acm_arn // ""' ${FILE})" "${ARN}"
  fi

  PUBLIC_HOST=$(yq '.hostname.public // ""' ${FILE})
  if [ "$(yq '.atlantis.acm_arn // ""' ${FILE})" != "" ]; then
    ARN=$(echo "${CERTS}" | awk -v d="${PUBLIC_HOST}" '$1==d {print $2; exit}')
    update ${FILE} "atlantis.acm_arn" "$(yq '.atlantis.acm_arn // ""' ${FILE})" "${ARN}"
  fi

  # target_group
  SUFFIX=$(yq '.istio.target_group // ""' ${FILE} | tr '_' '-')
  if [ -n "${SUFFIX}" ]; then
    PUBLIC_TG=$(aws elbv2 describe-target-groups --region ${REGION} --names "${ENV}-${SUFFIX}" \
      --query 'TargetGroups[0].TargetGroupArn' --output text 2>/dev/null || true)
    update ${FILE} "target_group.public_http" "$(yq '.target_group.public_http // ""' ${FILE})" "${PUBLIC_TG}"

    INTERNAL_TG=$(aws elbv2 describe-target-groups --region ${REGION} --names "${ENV}-in-${SUFFIX}" \
      --query 'TargetGroups[0].TargetGroupArn' --output text 2>/dev/null || true)
    update ${FILE} "target_group.internal_http" "$(yq '.target_group.internal_http // ""' ${FILE})" "${INTERNAL_TG}"
  fi
done

echo
echo "Done. Review with: git diff env/"
