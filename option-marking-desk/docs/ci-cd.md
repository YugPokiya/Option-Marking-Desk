# CI/CD: GitHub Actions → SonarQube → EC2 (CodeDeploy) or EKS

This repo ships with the pipeline below


```
.github/workflows/ci-cd.yml   the pipeline
sonar-project.properties      SonarQube project settings
.trivyignore.yaml             accepted Trivy findings (path-scoped, justified)
pytest.ini, requirements-dev.txt
tests/unit/, tests/integration/   example tests (adapt to your routes)
terraform/                    EC2 t3.micro + CodeDeploy infrastructure (see terraform/README.md)
deploy/codedeploy/            CodeDeploy revision: appspec, docker-compose, hook scripts
deploy/                       Kubernetes + Istio + EKS setup
```

## Pipeline

| Job | Runs on | Fails the build when |
|---|---|---|
| Lint + unit tests | every push / PR | ruff lint/format errors, unit test failures |
| Web | every push / PR | TypeScript errors, Vitest failures, Vite build failure |
| Integration tests | every push / PR | migrations don't apply/roll back on real Postgres 17 or drift from the models (`alembic check`), or integration tests fail against real Postgres + Redis |
| SonarQube | after both test jobs | quality gate fails (vulnerabilities, security hotspots, bugs, coverage on new code) |
| Trivy fs | every push / PR | HIGH/CRITICAL fixable CVEs in dependencies, leaked secrets, or Dockerfile/K8s misconfigurations |
| Build + scan image (api, web) | after tests | HIGH/CRITICAL fixable CVEs in the built image; on `main` the scanned image is pushed to ECR |
| Deploy to EC2 (default) | `main` only, after all of the above | CodeDeploy fails on any instance, or the 5xx alarm fires; CodeDeploy rolls back automatically |
| Deploy to EKS (`DEPLOY_TARGET=eks`) | `main` only, after all of the above | apply, migration or rollout fails, which triggers an automatic `rollout undo` |

Scan results also go to the repo's **Security → Code scanning** tab (free on public repos; private repos need GitHub Advanced Security, otherwise that upload step is skipped without failing).

## One-time setup

1. **SonarQube**: create the project with key `option-marking-desk` and generate a token.
   - On SonarQube Cloud, set `SONAR_HOST_URL=https://sonarcloud.io` and uncomment `sonar.organization`.
   - Make sure the quality gate includes "No new vulnerabilities" and "Security hotspots reviewed".
2. **AWS, EC2 path (default):** run `terraform apply` in `terraform/` and copy the outputs into GitHub variables (table in `terraform/README.md`).
   **AWS, EKS path:** the cluster must already exist (see `deploy/README.md`):
   ```bash
   GITHUB_REPO=YugPokiya/<repo> deploy/aws/github-oidc.sh
   ```
   This creates the GitHub OIDC provider and the `omd-github-deployer` role. Only `main` and the `production` environment can assume it. The role can push to the two ECR repos and has `eks:DescribeCluster`. Inside the cluster it's mapped to the `omd-deployers` group, which can only manage the `omd` namespace.
3. **GitHub → Settings → Secrets and variables → Actions**
   - Secrets: `SONAR_TOKEN` and `SONAR_HOST_URL` (plus `OMD_SECRETS_ENV` for EKS only; on EC2, secrets come from AWS)
   - Variables: `AWS_ROLE_ARN` and `ECR_REGISTRY`; for EC2 also `CODEDEPLOY_BUCKET`, `CODEDEPLOY_APP` and `CODEDEPLOY_GROUP`; `DEPLOY_TARGET=eks` only for Kubernetes
4. **GitHub → Settings → Environments → `production`**: add yourself as a required reviewer if you want to approve each deploy.
5. **Branch protection on `main`**: require the checks `Lint + unit tests`, `Web (typecheck, test, build)`, `Integration tests (Postgres + Redis)`, `SonarQube scan + quality gate`, `Trivy (dependencies, secrets, IaC)`, `Build + scan image (api)` and `Build + scan image (web)`.

## Run the tests locally

```bash
docker run -d --name pg -e POSTGRES_USER=omd -e POSTGRES_PASSWORD=omd -e POSTGRES_DB=omd_test -p 5432:5432 postgres:17-alpine
docker run -d --name rd -p 6379:6379 redis:7.4-alpine
pip install -r requirements.txt -r requirements-dev.txt
alembic upgrade head
pytest tests/unit
pytest -m integration tests/integration
```

## Notes

- Images are tagged with the commit SHA and ECR tags are immutable. The deployed image is exactly the one Trivy scanned.
- SonarQube Community Build analyses `main` only. PR decoration and branch analysis need Developer Edition or SonarQube Cloud.
- Third-party actions are pinned to commit SHAs (version in a comment), so a hijacked tag can't change the pipeline. Dependabot can keep them updated: add `.github/dependabot.yml` with the `github-actions` ecosystem.
