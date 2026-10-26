data "aws_kms_alias" "secretsmanager" {
  name = "alias/aws/secretsmanager"
}

# ---------- app instances ----------
resource "aws_iam_role" "app" {
  name = "${local.name}-app"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "app_ssm" {
  role       = aws_iam_role.app.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore" # Session Manager instead of SSH
}

resource "aws_iam_role_policy_attachment" "app_ecr" {
  role       = aws_iam_role.app.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

resource "aws_iam_role_policy" "app" {
  name = "app-runtime"
  role = aws_iam_role.app.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "CodeDeployRevisions"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:GetObjectVersion"]
        Resource = "${aws_s3_bucket.artifacts.arn}/*"
      },
      {
        Sid    = "CodeDeployAgent"
        Effect = "Allow"
        Action = [
          "codedeploy-commands-secure:GetDeploymentSpecification",
          "codedeploy-commands-secure:PollHostCommand",
          "codedeploy-commands-secure:PutHostCommandAcknowledgement",
          "codedeploy-commands-secure:PutHostCommandComplete",
        ]
        Resource = "*" # these actions do not support resource-level permissions
      },
      {
        Sid      = "AppConfig"
        Effect   = "Allow"
        Action   = ["ssm:GetParametersByPath", "ssm:GetParameters", "ssm:GetParameter"]
        Resource = ["arn:aws:ssm:${var.region}:${local.account_id}:parameter${local.param_path}", "arn:aws:ssm:${var.region}:${local.account_id}:parameter${local.param_path}/*"]
      },
      {
        Sid      = "DbSecret"
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = aws_db_instance.postgres.master_user_secret[0].secret_arn
      },
      {
        Sid      = "DecryptConfig"
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = [aws_kms_key.main.arn, data.aws_kms_alias.secretsmanager.target_key_arn]
      },
      {
        Sid    = "ClaudeReview"
        Effect = "Allow"
        Action = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        Resource = [
          "arn:aws:bedrock:${var.region}:${local.account_id}:inference-profile/${var.bedrock_model_id}",
          "arn:aws:bedrock:*::foundation-model/${local.bedrock_fm}*",
        ]
      },
      {
        Sid      = "AppLogs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
        Resource = "${aws_cloudwatch_log_group.app.arn}:*"
      },
    ]
  })
}

resource "aws_iam_instance_profile" "app" {
  name = "${local.name}-app"
  role = aws_iam_role.app.name
}

# ---------- CodeDeploy service ----------
resource "aws_iam_role" "codedeploy" {
  name = "${local.name}-codedeploy"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "codedeploy.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "codedeploy" {
  role       = aws_iam_role.codedeploy.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSCodeDeployRole"
}

# ---------- GitHub Actions (OIDC, no stored keys) ----------
resource "aws_iam_openid_connect_provider" "github" {
  count = var.github_repo != "" && var.create_github_oidc_provider ? 1 : 0

  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_openid_connect_provider" "github" {
  count = var.github_repo != "" && !var.create_github_oidc_provider ? 1 : 0
  url   = "https://token.actions.githubusercontent.com"
}

locals {
  github_oidc_arn = var.github_repo == "" ? "" : (
    var.create_github_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : data.aws_iam_openid_connect_provider.github[0].arn
  )
}

resource "aws_iam_role" "github" {
  count = var.github_repo == "" ? 0 : 1

  name = "${local.name}-github-codedeploy"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = local.github_oidc_arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com" }
        # main-branch pushes and the "production" environment only: no PRs, no forks
        StringLike = { "token.actions.githubusercontent.com:sub" = [
          "repo:${var.github_repo}:ref:refs/heads/main",
          "repo:${var.github_repo}:environment:production",
        ] }
      }
    }]
  })
}

resource "aws_iam_role_policy" "github" {
  count = var.github_repo == "" ? 0 : 1

  name = "push-and-deploy"
  role = aws_iam_role.github[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "EcrAuth"
        Effect   = "Allow"
        Action   = "ecr:GetAuthorizationToken"
        Resource = "*" # account-level call, no resource ARN
      },
      {
        Sid    = "EcrPush"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer",
        ]
        Resource = local.ecr_repo_arns
      },
      {
        Sid      = "UploadRevision"
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "${aws_s3_bucket.artifacts.arn}/*"
      },
      {
        Sid      = "EncryptRevision" # bucket uses the project KMS key
        Effect   = "Allow"
        Action   = ["kms:GenerateDataKey", "kms:Decrypt"]
        Resource = aws_kms_key.main.arn
      },
      {
        Sid    = "Deploy"
        Effect = "Allow"
        Action = [
          "codedeploy:CreateDeployment", "codedeploy:GetDeployment", "codedeploy:StopDeployment",
          "codedeploy:ListDeploymentTargets", "codedeploy:GetDeploymentTarget",
        ]
        Resource = [
          "arn:aws:codedeploy:${var.region}:${local.account_id}:deploymentgroup:${aws_codedeploy_app.app.name}/${aws_codedeploy_deployment_group.app.deployment_group_name}",
        ]
      },
      {
        Sid      = "DeployConfig"
        Effect   = "Allow"
        Action   = ["codedeploy:GetDeploymentConfig"]
        Resource = "arn:aws:codedeploy:${var.region}:${local.account_id}:deploymentconfig:*"
      },
      {
        Sid      = "Revisions"
        Effect   = "Allow"
        Action   = ["codedeploy:RegisterApplicationRevision", "codedeploy:GetApplicationRevision", "codedeploy:GetApplication"]
        Resource = "arn:aws:codedeploy:${var.region}:${local.account_id}:application:${aws_codedeploy_app.app.name}"
      },
    ]
  })
}
