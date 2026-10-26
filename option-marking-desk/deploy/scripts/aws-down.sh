#!/usr/bin/env bash
# Delete everything aws-up.sh created (stops the billing). ECR images are kept unless PURGE_ECR=1.
set -euo pipefail
REGION="${REGION:-ap-south-1}"
kubectl delete -k "$(cd "$(dirname "$0")/.." && pwd)/k8s/overlays/aws" --ignore-not-found || true
istioctl uninstall --purge -y || true          # removes the NLB before the VPC is torn down
eksctl delete cluster --name omd --region "$REGION" --wait
[[ "${PURGE_ECR:-0}" == 1 ]] && for r in omd-api omd-web; do aws ecr delete-repository --repository-name $r --region "$REGION" --force; done
echo "Note: the gp3 StorageClass uses reclaimPolicy Retain, so check for leftover EBS volumes:"
echo "  aws ec2 describe-volumes --region $REGION --filters Name=status,Values=available"
