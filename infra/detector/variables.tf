variable "region" {
  type    = string
  default = "ap-south-1"
}

variable "alert_email" {
  description = "Address that receives critical alerts. Set in detector.auto.tfvars (gitignored)."
  type        = string

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.alert_email))
    error_message = "alert_email must be an email address."
  }
}

variable "trail_log_retention_days" {
  type    = number
  default = 30
}

variable "event_ttl_days" {
  description = "How long clickops-events items live (the app writes expires_at accordingly)."
  type        = number
  default     = 90
}

variable "lambda_zip" {
  description = "Path to the zip built by scripts/build_lambda.sh."
  type        = string
  default     = "../../dist/clickops-detector.zip"
}

variable "trusted_role_arns" {
  description = "Extra role ARNs treated as CI, in addition to clickops-ci."
  type        = list(string)
  default     = []
}
