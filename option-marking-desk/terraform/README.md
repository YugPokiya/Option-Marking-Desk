# Terraform: EC2 (t3.micro) + CodeDeploy

The low-cost way to run the Option Marking Desk on AWS, without Kubernetes.

```
Internet ─► ALB (public subnets, HTTPS) ─► ASG: 2–4 × t3.micro (AL2023, Docker)
                                             │  nginx :80 ─► /api/* ─► FastAPI :8000
                                             ├─► RDS Postgres 17 (db.t3.micro, private, TLS forced)
                                             └─► ElastiCache Redis 7.1 (cache.t3.micro, TLS + auth)
GitHub Actions ─► ECR (images) + S3 (bundle) ─► CodeDeploy ─► one instance at a time, auto-rollback
```

## What gets created

| File | Resources |
|---|---|
| `network.tf` | VPC (2 AZs) with public, private and database subnets, flow logs, locked default security group |
| `security_groups.tf` | ALB (80/443 from the internet) → app (80 from the ALB only, no SSH) → DB (5432) / Redis (6379) |
| `alb.tf` | ALB, target group (health = `/api/readyz`), HTTP→HTTPS redirect when `certificate_arn` is set |
| `compute.tf` | Launch template (AL2023, IMDSv2, encrypted gp3, `standard` CPU credits), ASG, CPU target-tracking |
| `user_data.sh.tftpl` | First boot: Docker + Compose, 1 GiB swap, CodeDeploy agent |
| `codedeploy.tf` | App + deployment group: in-place, `OneAtATime`, ALB traffic control, rollback on failure or 5xx alarm |
| `rds.tf` | Postgres 17, password in Secrets Manager (`manage_master_user_password`), 7-day backups |
| `elasticache.tf` | Redis 7.1, encrypted in transit and at rest, auth token |
| `ssm.tf` | Runtime config under `/omd/prod/*` (SecureString), which the instances read on each deploy |
| `ecr.tf`, `s3.tf` | Image repos (immutable tags, scan on push) and the CodeDeploy bundle bucket (KMS, TLS-only, lifecycle) |
| `iam.tf` | Instance role (SSM, ECR pull, its own config/secret/logs only), CodeDeploy role, GitHub OIDC role |
| `kms.tf`, `monitoring.tf` | Project KMS key; app log group; SNS alarms for 5xx, unhealthy hosts, DB CPU/storage and low CPU credits |

## Deploy

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars      # set github_repo; see the comments for other options
terraform init
terraform plan -out tfplan
terraform apply tfplan                            # ~15 min, mostly RDS and ElastiCache
terraform output
```

Then in **GitHub → Settings → Secrets and variables → Actions → Variables**:

| Variable | From |
|---|---|
| `AWS_ROLE_ARN` | `terraform output -raw github_role_arn` |
| `ECR_REGISTRY` | `terraform output -raw ecr_registry` |
| `CODEDEPLOY_BUCKET` | `terraform output -raw codedeploy_bucket` |
| `CODEDEPLOY_APP` | `terraform output -raw codedeploy_app` |
| `CODEDEPLOY_GROUP` | `terraform output -raw codedeploy_group` |
| `DEPLOY_TARGET` | `ec2` (or leave unset, since ec2 is the default) |

Push to `main`. The pipeline tests and scans, then pushes the images, uploads `deploy/codedeploy` as the revision and runs CodeDeploy.

**After the first successful deployment**, set `asg_health_check_type = "ELB"` and apply again. Until then the ASG uses EC2 checks, because brand-new instances have no app and would otherwise be replaced in a loop.

## How a deployment runs on each instance

`deploy/codedeploy/appspec.yml`:
1. CodeDeploy takes one instance out of the ALB.
2. `stop.sh` runs `docker compose down` on the old release.
3. `configure.sh` reads `/omd/prod/*` from SSM and the DB password from Secrets Manager. It writes `/opt/omd/.env` (mode 600) and pulls the images for this commit.
4. `start.sh` runs `alembic upgrade head`, then `docker compose up --wait`.
5. `validate.sh` waits for `/api/readyz`, which checks Postgres and Redis, then CodeDeploy puts the instance back in the ALB.

Steps 1–5 repeat for the next instance. Any failure, or the 5xx alarm firing, rolls back to the previous revision.

Container logs go to CloudWatch `/omd/prod/app`. For a shell on an instance, use `aws ssm start-session --target <instance-id>`; there's no SSH.

## Cost (rough, ap-south-1, on demand; check the AWS Pricing Calculator)

| Item | ≈ USD/month |
|---|---|
| 2 × t3.micro + 2 × 20 GB gp3 | 15–20 |
| ALB | 18–25 |
| RDS db.t3.micro + 20 GB | 15–20 |
| ElastiCache cache.t3.micro | 12–15 |
| KMS key, CloudWatch, S3, ECR | 3–6 |
| NAT gateway (only if `use_nat_gateway = true`) | +35 plus data |

To stop paying for a test stack, set `deletion_protection = false`, apply, then run `terraform destroy`.

## Notes on t3.micro

- **1 GiB RAM:** the API container is capped at 640 MB, uses 1 uvicorn worker, and the instance has 1 GiB swap. If smile fitting needs more, use `t3.small`; nothing else changes.
- **CPU credits:** set to `standard`, so there's no surprise bill. Once credits run out the instance is held to 10% CPU, and the `cpu-credits-low` alarm warns you first.

## Checked offline (no AWS account here)

These passed: `tofu fmt`, TFLint with the AWS ruleset, Trivy (0 HIGH/CRITICAL after the 3 justified exceptions in `/.trivyignore.yaml`), a reference cross-check, and every resource argument checked against the AWS provider v6.70 source. `terraform plan` hasn't been run, so treat the first `plan` as the real test.

Checkov reports 20 remaining items, all deliberate cost or simplicity trade-offs: WAF, Multi-AZ RDS/Redis, RDS Performance Insights and enhanced monitoring, 1-year log retention, S3 access logs and replication, ALB access logs, and the HTTP-only listener before a certificate is set. Add whichever ones your use needs.
