#!/usr/bin/env bash
# Shift live /api traffic to omd-api v2.   Usage: scripts/canary.sh <percent to v2>
# Requires the canary component to be deployed (see overlays/prod/kustomization.yaml).
set -euo pipefail
P="${1:?percent for v2 (0-100)}"; (( P>=0 && P<=100 )) || { echo "0-100"; exit 1; }
kubectl -n omd patch virtualservice omd --type json -p "[
  {\"op\":\"replace\",\"path\":\"/spec/http/0/route\",\"value\":[
    {\"destination\":{\"host\":\"omd-api\",\"subset\":\"v1\",\"port\":{\"number\":80}},\"weight\":$((100-P))},
    {\"destination\":{\"host\":\"omd-api\",\"subset\":\"v2\",\"port\":{\"number\":80}},\"weight\":$P}]}]"
echo "v1=$((100-P))%  v2=$P%"
echo "watch errors: kubectl -n istio-system logs deploy/istio-ingressgateway -f | grep '\"response_code\":5'"
