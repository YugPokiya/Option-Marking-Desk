# Security

Please report vulnerabilities privately through **GitHub → Security → Report a vulnerability**
(private vulnerability reporting), not in public issues.

Every push is scanned. SonarQube checks the code (quality gate), and Trivy checks dependencies, secrets, IaC and the built images.
Accepted findings are listed with reasons in `.trivyignore.yaml`.
