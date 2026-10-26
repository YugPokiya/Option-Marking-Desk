#!/usr/bin/env bash
# One-time: let GitHub Actions in OWNER/REPO deploy without stored AWS keys.
# Usage: GITHUB_REPO=YugPokiya/option-marking-desk deploy/aws/github-oidc.sh
# Prints the AWS_ROLE_ARN and ECR_REGISTRY values to save as GitHub repo variables.
set -euo pipefail
REPO="${GITHUB_REPO:?owner/repo}"; REGION="${REGION:-ap-south-1}"; CLUSTER=omd; ROLE=omd-github-deployer
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
OIDC_ARN="arn:aws:iam::$ACCOUNT:oidc-provider/token.actions.githubusercontent.com"

aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$OIDC_ARN" >/dev/null 2>&1 || \
  aws iam create-open-id-connect-provider --url https://token.actions.githubusercontent.com \
    --client-id-list sts.amazonaws.com >/dev/null

# Only main-branch pushes and the "production" environment may assume the role (no PRs, no forks).
cat > /tmp/trust.json <<JSON
{"Version":"2012-10-17","Statement":[{"Effect":"Allow",
 "Principal":{"Federated":"$OIDC_ARN"},"Action":"sts:AssumeRoleWithWebIdentity",
 "Condition":{"StringEquals":{"token.actions.githubusercontent.com:aud":"sts.amazonaws.com"},
  "StringLike":{"token.actions.githubusercontent.com:sub":["repo:$REPO:ref:refs/heads/main","repo:$REPO:environment:production"]}}}]}
JSON
cat > /tmp/perms.json <<JSON
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow","Action":"ecr:GetAuthorizationToken","Resource":"*"},
 {"Effect":"Allow","Action":["ecr:BatchCheckLayerAvailability","ecr:InitiateLayerUpload","ecr:UploadLayerPart",
   "ecr:CompleteLayerUpload","ecr:PutImage","ecr:BatchGetImage","ecr:GetDownloadUrlForLayer"],
  "Resource":["arn:aws:ecr:$REGION:$ACCOUNT:repository/omd-api","arn:aws:ecr:$REGION:$ACCOUNT:repository/omd-web"]},
 {"Effect":"Allow","Action":"eks:DescribeCluster","Resource":"arn:aws:eks:$REGION:$ACCOUNT:cluster/$CLUSTER"}]}
JSON
aws iam get-role --role-name $ROLE >/dev/null 2>&1 || \
  aws iam create-role --role-name $ROLE --assume-role-policy-document file:///tmp/trust.json >/dev/null
aws iam update-assume-role-policy --role-name $ROLE --policy-document file:///tmp/trust.json
aws iam put-role-policy --role-name $ROLE --policy-name omd-deploy --policy-document file:///tmp/perms.json
ROLE_ARN=$(aws iam get-role --role-name $ROLE --query Role.Arn --output text)

# Map the role into Kubernetes as group "omd-deployers" (permissions in ci-deployer-rbac.yaml).
aws eks create-access-entry --cluster-name $CLUSTER --region "$REGION" --principal-arn "$ROLE_ARN" \
  --kubernetes-groups omd-deployers >/dev/null 2>&1 || echo "(access entry exists)"
kubectl apply -f "$ROOT/k8s/platform/ci-deployer-rbac.yaml"

echo
echo "GitHub repo variables:"
echo "  AWS_ROLE_ARN = $ROLE_ARN"
echo "  ECR_REGISTRY = $ACCOUNT.dkr.ecr.$REGION.amazonaws.com"
