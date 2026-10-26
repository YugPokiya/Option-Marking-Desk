resource "aws_codedeploy_app" "app" {
  name             = local.name
  compute_platform = "Server"
}

resource "aws_codedeploy_deployment_group" "app" {
  app_name               = aws_codedeploy_app.app.name
  deployment_group_name  = "${local.name}-app"
  service_role_arn       = aws_iam_role.codedeploy.arn
  deployment_config_name = "CodeDeployDefault.OneAtATime" # one instance out of the ALB at a time
  autoscaling_groups     = [aws_autoscaling_group.app.name]

  # new instances launched by the ASG get the last successful revision automatically
  outdated_instances_strategy = "UPDATE"

  deployment_style {
    deployment_option = "WITH_TRAFFIC_CONTROL" # deregister from the ALB, deploy, re-register
    deployment_type   = "IN_PLACE"
  }

  load_balancer_info {
    target_group_info {
      name = aws_lb_target_group.app.name
    }
  }

  auto_rollback_configuration {
    enabled = true
    events  = ["DEPLOYMENT_FAILURE", "DEPLOYMENT_STOP_ON_ALARM"]
  }

  alarm_configuration {
    enabled = true
    alarms  = [aws_cloudwatch_metric_alarm.target_5xx.alarm_name]
  }
}
