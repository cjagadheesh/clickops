output "security_group_ids" {
  value = {
    web   = aws_security_group.web.id
    admin = aws_security_group.admin.id
  }
}

output "role_name" {
  value = aws_iam_role.app.name
}

output "bucket" {
  value = aws_s3_bucket.main.bucket
}

output "lambda_name" {
  value = aws_lambda_function.hello.function_name
}

output "zone_id" {
  value = aws_route53_zone.private.zone_id
}
