output "state_bucket" {
  description = "Backend bucket for the sandbox and detector roots."
  value       = aws_s3_bucket.state.bucket
}

output "ci_role_arn" {
  description = "Role assumed by GitHub Actions through OIDC."
  value       = aws_iam_role.ci.arn
}
