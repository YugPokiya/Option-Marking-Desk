#!/usr/bin/env bash
# One-time cluster setup + first deploy.   Usage: scripts/bootstrap.sh dev|prod
set -euo pipefail
ENV="${1:?usage: $0 dev|prod}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ISTIO_VERSION="${ISTIO_VERSION:-1.31.3}"

for bin in kubectl istioctl helm; do command -v "$bin" >/dev/null || { echo "missing $bin"; exit 1; }; done
istioctl version --remote=false | grep -q "$ISTIO_VERSION" || echo "warning: istioctl is not $ISTIO_VERSION"
[[ -f "$ROOT/k8s/overlays/$ENV/secrets.env" ]] || { echo "create k8s/overlays/$ENV/secrets.env from the .example first"; exit 1; }

echo "==> Istio $ISTIO_VERSION"
istioctl x precheck
istioctl install -f "$ROOT/istio/istio-operator.yaml" -y
kubectl -n istio-system rollout status deploy/istiod
kubectl -n istio-system rollout status deploy/istio-ingressgateway

echo "==> cert-manager"
helm upgrade --install cert-manager oci://quay.io/jetstack/charts/cert-manager \
  -n cert-manager --create-namespace --set crds.enabled=true --wait
if ! kubectl -n cert-manager get secret do-dns-token >/dev/null 2>&1; then
  : "${DO_TOKEN:?export DO_TOKEN=<DigitalOcean API token with DNS write> for the DNS-01 solver}"
  kubectl -n cert-manager create secret generic do-dns-token --from-literal=access-token="$DO_TOKEN"
fi
kubectl apply -f "$ROOT/k8s/platform/cert-manager.yaml"

echo "==> app ($ENV)"
kubectl apply -k "$ROOT/k8s/overlays/$ENV"
"$ROOT/scripts/migrate.sh"
kubectl -n omd rollout status deploy/omd-api
kubectl -n omd rollout status deploy/omd-web

echo "==> checks"
istioctl analyze -n omd
LB=$(kubectl -n istio-system get svc istio-ingressgateway -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo "Ingress IP: ${LB:-<pending>}  -> point your DNS A record(s) at it."
