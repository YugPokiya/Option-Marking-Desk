#!/usr/bin/env bash
# Create EKS + ECR, push images, install Istio/cert-manager, deploy the app.
# Usage: TAG=0.1.0 deploy/scripts/aws-up.sh     (run from anywhere; builds from the repo root)
#   expects app/ and web/ at the repo root, this folder at deploy/
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REGION="${REGION:-ap-south-1}"; CLUSTER=omd; TAG="${TAG:-0.1.0}"
APP_DIR="$(cd "$ROOT/.." && pwd)"
for b in aws eksctl kubectl istioctl helm docker; do command -v $b >/dev/null || { echo "missing $b"; exit 1; }; done
[[ -f "$ROOT/k8s/overlays/aws/secrets.env" ]] || { echo "create k8s/overlays/aws/secrets.env from the .example"; exit 1; }

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
ECR="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"
echo "==> account $ACCOUNT, region $REGION"

echo "==> EKS cluster (skipped if it exists)"
eksctl get cluster --name $CLUSTER --region $REGION >/dev/null 2>&1 || eksctl create cluster -f "$ROOT/aws/cluster.yaml"
aws eks update-kubeconfig --name $CLUSTER --region $REGION
kubectl apply -f "$ROOT/aws/storageclass-gp3.yaml"

echo "==> ECR repos + images"
for r in omd-api omd-web; do
  aws ecr describe-repositories --repository-names $r --region $REGION >/dev/null 2>&1 || \
    aws ecr create-repository --repository-name $r --region $REGION \
      --image-scanning-configuration scanOnPush=true --image-tag-mutability IMMUTABLE >/dev/null
done
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin "$ECR"
docker build --platform linux/amd64 -f "$ROOT/docker/api.Dockerfile" -t "$ECR/omd-api:$TAG" "$APP_DIR"
docker build --platform linux/amd64 -f "$ROOT/docker/web.Dockerfile" -t "$ECR/omd-web:$TAG" "$APP_DIR"
docker push "$ECR/omd-api:$TAG"; docker push "$ECR/omd-web:$TAG"
sed -i "s|[0-9]\{12\}\.dkr\.ecr\.[a-z0-9-]*\.amazonaws\.com|$ECR|g; s|newTag: .*}|newTag: $TAG}|" "$ROOT/k8s/overlays/aws/kustomization.yaml"

echo "==> Istio"
istioctl install -f "$ROOT/istio/istio-operator-aws.yaml" -y

echo "==> cert-manager (Route 53 via Pod Identity)"
helm upgrade --install cert-manager oci://quay.io/jetstack/charts/cert-manager \
  -n cert-manager --create-namespace --set crds.enabled=true --wait
kubectl apply -f "$ROOT/aws/cert-manager-route53.yaml"

echo "==> app"
kubectl apply -k "$ROOT/k8s/overlays/aws"
kubectl -n omd rollout status statefulset/postgres --timeout=300s
sed "s|image: .*omd-api:.*|image: $ECR/omd-api:$TAG|" "$ROOT/k8s/jobs/migrate.yaml" | kubectl create -f - -o name | tee /tmp/omd-job
kubectl -n omd wait --for=condition=complete "$(cat /tmp/omd-job)" --timeout=300s
kubectl -n omd rollout status deploy/omd-api
kubectl -n omd rollout status deploy/omd-web
istioctl analyze -n omd

NLB=$(kubectl -n istio-system get svc istio-ingressgateway -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
echo "NLB: $NLB"
echo "Create a Route 53 alias (or CNAME) for omd.example.com -> $NLB"
