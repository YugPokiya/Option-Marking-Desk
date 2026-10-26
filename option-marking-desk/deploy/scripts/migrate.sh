#!/usr/bin/env bash
# Runs Alembic migrations as a one-off Job and waits for it.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
JOB=$(kubectl create -f "$ROOT/k8s/jobs/migrate.yaml" -o name)
echo "started $JOB"
kubectl -n omd wait --for=condition=complete "$JOB" --timeout=300s || {
  kubectl -n omd logs "$JOB" -c migrate --tail=100; exit 1; }
