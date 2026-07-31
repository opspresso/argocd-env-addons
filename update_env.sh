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

# Step logging colors. Disabled when stdout is not a terminal.
if [ -t 1 ]; then
  C_STEP='\033[1;36m' # cyan   - step
  C_CMD='\033[0;33m'  # yellow - aws lookup
  C_OK='\033[0;32m'   # green  - updated
  C_DIM='\033[0;90m'  # gray   - unchanged / skipped
  C_ERR='\033[0;31m'  # red    - error
  C_OFF='\033[0m'
else
  C_STEP='' C_CMD='' C_OK='' C_DIM='' C_ERR='' C_OFF=''
fi

step() { echo -e "\n${C_STEP}==> $*${C_OFF}"; }
lookup() { echo -e "${C_CMD}  aws  $*${C_OFF}"; }
changed() { echo -e "${C_OK}  $*${C_OFF}"; }
skip() { echo -e "${C_DIM}  $*${C_OFF}"; }
ok() { echo -e "\n${C_OK}✔ $*${C_OFF}"; }
die() {
  echo -e "${C_ERR}✘ $*${C_OFF}" >&2
  exit 1
}

step "Checking prerequisites"

command -v yq >/dev/null || die "yq is required"
echo -e "${C_DIM}  yq  $(command -v yq)${C_OFF}"

lookup "sts get-caller-identity"
CURRENT_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
echo -e "${C_DIM}  account ${CURRENT_ACCOUNT_ID}${C_OFF}"

update() {
  FILE=$1
  KEY=$2
  OLD=$3
  NEW=$4

  if [ -z "${NEW}" ] || [ "${NEW}" == "None" ] || [ "${NEW}" == "null" ]; then
    skip "${KEY}: not found in aws, skipped"
    return
  fi

  if [ -z "${OLD}" ] || [ "${OLD}" == "null" ]; then
    skip "${KEY}: not set in file, skipped"
    return
  fi

  if [ "${OLD}" == "${NEW}" ]; then
    skip "${KEY}: unchanged"
    return
  fi

  perl -pi -e "s|\Q${OLD}\E|${NEW}|" ${FILE}
  changed "${KEY}: ${OLD} -> ${NEW}"
}

for FILE in ${SHELL_DIR}/env/*.yaml; do
  step "Processing ${FILE}"

  ENV=$(yq '.env' ${FILE})
  ACCOUNT_ID=$(yq '.aws_account_id' ${FILE})
  REGION=$(yq '.aws_region' ${FILE})

  if [ "${ACCOUNT_ID}" != "${CURRENT_ACCOUNT_ID}" ]; then
    skip "skipped: aws_account_id ${ACCOUNT_ID} != current account ${CURRENT_ACCOUNT_ID}"
    continue
  fi

  # vpcId
  lookup "ec2 describe-vpcs --filters Name=tag:Name,Values=vpc-${ENV}"
  VPC_ID=$(aws ec2 describe-vpcs --region ${REGION} \
    --filters "Name=tag:Name,Values=vpc-${ENV}" \
    --query 'Vpcs[0].VpcId' --output text)
  update ${FILE} "vpcId" "$(yq '.vpcId // ""' ${FILE})" "${VPC_ID}"

  # acm_arn
  lookup "acm list-certificates --certificate-statuses ISSUED"
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
  #
  # public and internal no longer share one suffix: the public groups were
  # renamed to *-h1-* when they moved to protocol_version HTTP1 (an ALB cannot
  # change that in place, so the group is replaced and the name has to differ).
  # `target_group_public` overrides for that; unset keeps the old shared name.
  SUFFIX=$(yq '.istio.target_group // ""' ${FILE} | tr '_' '-')
  PUBLIC_SUFFIX=$(yq '.istio.target_group_public // ""' ${FILE} | tr '_' '-')
  [ -z "${PUBLIC_SUFFIX}" ] && PUBLIC_SUFFIX="${SUFFIX}"
  GRPC_SUFFIX=$(yq '.istio.target_group_grpc // ""' ${FILE} | tr '_' '-')
  if [ -n "${SUFFIX}" ]; then
    lookup "elbv2 describe-target-groups --names ${ENV}-${PUBLIC_SUFFIX}"
    PUBLIC_TG=$(aws elbv2 describe-target-groups --region ${REGION} --names "${ENV}-${PUBLIC_SUFFIX}" \
      --query 'TargetGroups[0].TargetGroupArn' --output text 2>/dev/null || true)
    update ${FILE} "target_group.public_http" "$(yq '.target_group.public_http // ""' ${FILE})" "${PUBLIC_TG}"

    # gRPC needs h2 to the backend, which an HTTP1 group cannot carry, so it has
    # its own. Optional: an env without one simply has no gRPC host.
    if [ -n "${GRPC_SUFFIX}" ]; then
      lookup "elbv2 describe-target-groups --names ${ENV}-${GRPC_SUFFIX}"
      GRPC_TG=$(aws elbv2 describe-target-groups --region ${REGION} --names "${ENV}-${GRPC_SUFFIX}" \
        --query 'TargetGroups[0].TargetGroupArn' --output text 2>/dev/null || true)
      update ${FILE} "target_group.public_grpc" "$(yq '.target_group.public_grpc // ""' ${FILE})" "${GRPC_TG}"
    fi

    lookup "elbv2 describe-target-groups --names ${ENV}-in-${SUFFIX}"
    INTERNAL_TG=$(aws elbv2 describe-target-groups --region ${REGION} --names "${ENV}-in-${SUFFIX}" \
      --query 'TargetGroups[0].TargetGroupArn' --output text 2>/dev/null || true)
    update ${FILE} "target_group.internal_http" "$(yq '.target_group.internal_http // ""' ${FILE})" "${INTERNAL_TG}"
  fi
done

ok "Done. Review with: git diff env/"
