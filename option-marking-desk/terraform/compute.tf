data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

resource "aws_launch_template" "app" {
  name_prefix            = "${local.name}-app-"
  image_id               = data.aws_ssm_parameter.al2023.value
  instance_type          = var.instance_type
  update_default_version = true

  iam_instance_profile {
    arn = aws_iam_instance_profile.app.arn
  }

  # "standard" = no surprise charges when the burst credits run out (t3 defaults to "unlimited")
  credit_specification {
    cpu_credits = "standard"
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required" # IMDSv2 only
    http_put_response_hop_limit = 1          # only the host calls AWS; containers get no instance credentials
  }

  monitoring {
    enabled = true
  }

  network_interfaces {
    associate_public_ip_address = !var.use_nat_gateway
    security_groups             = [aws_security_group.app.id]
    delete_on_termination       = true
  }

  block_device_mappings {
    device_name = "/dev/xvda"

    ebs {
      volume_size           = 20
      volume_type           = "gp3"
      encrypted             = true
      delete_on_termination = true
    }
  }

  user_data = base64encode(templatefile("${path.module}/user_data.sh.tftpl", {
    region          = var.region
    compose_version = var.compose_version
  }))

  tag_specifications {
    resource_type = "instance"
    tags          = merge(local.tags, { Name = "${local.name}-app" })
  }

  tag_specifications {
    resource_type = "volume"
    tags          = merge(local.tags, { Name = "${local.name}-app" })
  }
}

resource "aws_autoscaling_group" "app" {
  name                      = "${local.name}-app"
  min_size                  = var.asg_min_size
  desired_capacity          = var.asg_desired_capacity
  max_size                  = var.asg_max_size
  vpc_zone_identifier       = local.app_subnet_ids
  target_group_arns         = [aws_lb_target_group.app.arn]
  health_check_type         = var.asg_health_check_type
  health_check_grace_period = 300
  default_instance_warmup   = 120

  launch_template {
    id      = aws_launch_template.app.id
    version = aws_launch_template.app.latest_version
  }

  # A new launch template (e.g. a newer AMI) replaces instances gradually.
  instance_refresh {
    strategy = "Rolling"

    preferences {
      min_healthy_percentage = 50
    }
  }

  tag {
    key                 = "Name"
    value               = "${local.name}-app"
    propagate_at_launch = true
  }

  lifecycle {
    ignore_changes = [desired_capacity] # owned by the scaling policy after creation
  }
}

resource "aws_autoscaling_policy" "cpu" {
  name                   = "${local.name}-cpu-target"
  autoscaling_group_name = aws_autoscaling_group.app.name
  policy_type            = "TargetTrackingScaling"

  target_tracking_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ASGAverageCPUUtilization"
    }
    target_value = 60
  }
}
