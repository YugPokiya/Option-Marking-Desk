resource "aws_ecr_repository" "app" {
  for_each = var.create_ecr_repositories ? toset(local.ecr_repo_names) : toset([])

  name                 = each.value
  image_tag_mutability = "IMMUTABLE" # images are tagged with the git SHA; a tag always means one image

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "app" {
  for_each = aws_ecr_repository.app

  repository = each.value.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 30 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 30
      }
      action = { type = "expire" }
    }]
  })
}
