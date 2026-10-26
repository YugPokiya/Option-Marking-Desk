#!/usr/bin/env bash
# Offline checks: render every overlay, schema-check it (incl. Istio CRDs), run istioctl analyze.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CRDS='https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json'
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
cp -r "$ROOT/k8s" "$TMP/k8s"                      # work on a copy; never touch real secrets.env
for d in "$TMP"/k8s/overlays/*/; do [[ -f "$d/secrets.env" ]] || cp "$d/secrets.env.example" "$d/secrets.env"; done
mkdir -p "$TMP/k8s/overlays/prod-canary"
cat > "$TMP/k8s/overlays/prod-canary/kustomization.yaml" <<'K'
resources: [../prod]
components: [../../components/canary]
K
for ENV in dev prod prod-canary aws; do
  echo "== $ENV"
  kustomize build "$TMP/k8s/overlays/$ENV" > "$TMP/$ENV.yaml"
  kubeconform -strict -summary -kubernetes-version 1.33.0 \
    -schema-location default -schema-location "$CRDS" "$TMP/$ENV.yaml"
  istioctl analyze --use-kube=false --meshConfigFile "$ROOT/istio/meshconfig-analyze.yaml" "$TMP/$ENV.yaml"
done
echo "== platform + jobs"
kubeconform -strict -summary -schema-location default -schema-location "$CRDS" \
  "$ROOT/k8s/jobs/migrate.yaml" "$ROOT/k8s/platform/cert-manager.yaml" "$ROOT/aws/cert-manager-route53.yaml" "$ROOT/aws/storageclass-gp3.yaml"
for f in istio-operator istio-operator-aws; do istioctl manifest generate -f "$ROOT/istio/$f.yaml" > /dev/null && echo "$f OK"; done
