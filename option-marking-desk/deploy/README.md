# Option Marking Desk: Kubernetes + Istio

Deployment setup for the Option Marking Desk web app on DigitalOcean Kubernetes (DOKS) with Istio 1.31.3.

```
             Internet
                │  HTTPS (Let's Encrypt, DNS-01)
     ┌──────────▼───────────┐   istio-system
     │ istio-ingressgateway │   (DO LoadBalancer)
     └───┬──────────────┬───┘
   /api/*│              │ /*            ── all hops below are mTLS (STRICT) ──
 ┌───────▼──────┐  ┌────▼────┐          namespace: omd  (deny-all + allow-list)
 │ omd-api v1/v2│  │ omd-web │
 │ FastAPI, HPA │  │ nginx   │
 └──┬────────┬──┘  └─────────┘
    │        │
┌───▼────┐ ┌─▼─────┐
│postgres│ │ redis │        prod: postgres -> DO Managed Postgres (ServiceEntry)
└────────┘ └───────┘
```

## Assumptions about the app (change these if yours differ)

| Assumed | Where it's set |
|---|---|
| FastAPI app at `app/main.py`, port 8000. Istio strips `/api`, so routes are `/marks`, `/healthz`… and `FastAPI(root_path=os.getenv("API_ROOT_PATH",""))` keeps `/api/docs` working | `docker/api.Dockerfile`, `k8s/base/istio/virtualservice.yaml` |
| Endpoints `/healthz` (process alive) and `/readyz` (DB + Redis ok) | probes in `k8s/base/api.yaml` |
| `/metrics` Prometheus endpoint (blocked from the internet) | pod annotations, `allow-gateway-to-api` policy |
| Alembic migrations (`alembic upgrade head`) | `k8s/jobs/migrate.yaml` |
| Vite/React frontend in `web/`, built to `web/dist/`; images build from the repo root | `docker/web.Dockerfile` |
| Images in DO Container Registry `registry.digitalocean.com/omd/` | `images:` in each overlay |
| Domain `omd.example.com` / `dev.omd.example.com` | gateway, virtual service, certificate, dev overlay |

## Layout

```
istio/istio-operator.yaml      Istio install: istiod + ingress gateway, REGISTRY_ONLY egress, native sidecars, JSON access logs
k8s/base/                      namespace (injection on), API, web, Postgres, Redis, HPA, PDBs
k8s/base/istio/                Gateway, VirtualService, DestinationRules, STRICT mTLS, AuthorizationPolicies, Sidecar scope
k8s/overlays/dev|prod/         per-env images, replicas, hosts, secrets; prod swaps in managed Postgres
k8s/components/canary/         omd-api v2 + 90/10 traffic split (opt-in from prod)
k8s/platform/cert-manager.yaml ClusterIssuer (DigitalOcean DNS-01) + Certificate in istio-system
k8s/jobs/migrate.yaml          one-off Alembic Job per release
docker/                        API + web Dockerfiles, nginx.conf
scripts/                       bootstrap, migrate, canary, validate
```

## First deploy

Prereqs: `kubectl` pointed at a DOKS cluster (Kubernetes 1.29+), `istioctl` 1.31.3, `helm`, a DO API token with DNS write access, and your domain on DO DNS.

```bash
cp k8s/overlays/dev/secrets.env.example k8s/overlays/dev/secrets.env   # edit passwords
export DO_TOKEN=dop_v1_...                                              # for the DNS-01 challenge
make bootstrap ENV=dev
# point an A record for dev.omd.example.com at the printed ingress IP
```

`bootstrap` runs: `istioctl x precheck` → install Istio → cert-manager (Helm) → TLS issuer/cert → `kubectl apply -k` → migration Job → rollout wait → `istioctl analyze`.

After that, for each release:

```bash
make diff ENV=prod      # review
make deploy ENV=prod    # apply, migrate, wait
make status             # pods, HPA, proxy sync, istioctl analyze
```

## What each Istio piece does

- **PeerAuthentication `STRICT`**: pods in `omd` only accept mTLS. Plain-text connections from outside the mesh are refused.
- **AuthorizationPolicies**: `deny-all` first, then only these hops are allowed:
  - the gateway to web (GET/HEAD)
  - the gateway to the API (everything except `/metrics`)
  - the API to Redis
  - the API and the migration Job to Postgres

  Each identity comes from its ServiceAccount.
- **VirtualService**: sends `/api` to the API, stripping the prefix, and everything else to web. The API route has a 30s timeout and retries only on connection failures, so a POST that recomputes marks is never replayed.
- **DestinationRule**: sets connection limits and outlier detection, which ejects a pod after 5 consecutive 5xx errors. It also defines the `v1`/`v2` subsets used by the canary.
- **Sidecar**: each Envoy proxy only learns about services in `omd` and `istio-system`.
- **REGISTRY_ONLY egress** (mesh-wide): outbound calls must be declared. Prod declares the managed DB in `managed-postgres.yaml`. **If the marking engine pulls market data from an external API, add a ServiceEntry for that host.**
- **Native sidecars**: the proxy starts before the app, and Jobs (migrations) finish instead of hanging on Envoy.

## Canary a new marking-engine build

1. In `k8s/overlays/prod/kustomization.yaml`, uncomment `components: - ../../components/canary`.
2. Set the v2 tag in `k8s/components/canary/kustomization.yaml`.
3. Run `make deploy ENV=prod`. This sends 10% of traffic to v2.
4. Watch the 5xx errors, then shift traffic with `make canary P=50` and `make canary P=100`.
5. Promote: set v1's image tag to the new version, comment the component out again and deploy.

Note: `make canary` patches the live VirtualService. The next `make deploy` resets the weights to what's in git.

## Deploy on AWS (EKS) with the CLI

Files: `aws/cluster.yaml` (eksctl), `aws/storageclass-gp3.yaml`, `aws/cert-manager-route53.yaml`, `istio/istio-operator-aws.yaml` (NLB), `k8s/overlays/aws/`, `scripts/aws-up.sh`, `scripts/aws-down.sh`.

Prereqs: `aws` CLI v2 configured (`aws configure`), plus `eksctl`, `kubectl`, `helm`, `istioctl` 1.31.3 and Docker. Your domain must be a Route 53 hosted zone. Set its zone ID in `aws/cert-manager-route53.yaml`.

```bash
cp k8s/overlays/aws/secrets.env.example k8s/overlays/aws/secrets.env
TAG=0.1.0 deploy/scripts/aws-up.sh
```

`aws-up.sh` runs these steps:

1. `eksctl create cluster` for EKS 1.36 in ap-south-1: 3× m6i.large on private subnets, the EBS CSI driver, and Pod Identity for cert-manager.
2. Create the ECR repos (scan on push, immutable tags), then build and push both images.
3. Install Istio behind an internet-facing NLB.
4. Install cert-manager, which uses Route 53 DNS-01 with no stored keys.
5. `kubectl apply -k k8s/overlays/aws`.
6. Run the migration Job and wait for the rollouts.

Finally, create a Route 53 alias for your domain pointing at the NLB hostname the script prints.

Teardown: `scripts/aws-down.sh` (add `PURGE_ECR=1` to delete the images too). Leaving the cluster running costs roughly the EKS control plane + 3 m6i.large + an NLB + EBS, so tear it down when you're not using it.

## Validate offline

```bash
make validate
```

This renders dev, prod and prod+canary, schema-checks every object (including the Istio and cert-manager CRDs) with kubeconform, runs `istioctl analyze` on each render, and dry-runs the IstioOperator. The current files pass with 0 errors.

## Notes

- Secrets come from a git-ignored `secrets.env` per overlay. Hash suffixes are off, so the migration Job can reference `omd-secrets`, which means a secret change needs `kubectl -n omd rollout restart deploy/omd-api`. For real prod, consider External Secrets or Sealed Secrets.
- In-cluster Postgres (dev) is a single replica on a 10Gi DO block volume, with no backups.
- Redis is cache-only (no persistence, LRU at 200MB).
- Observability: Istio metrics are merged on `:15020`. To view them, add the Prometheus, Grafana and Kiali addons from the Istio release `samples/addons/`.
