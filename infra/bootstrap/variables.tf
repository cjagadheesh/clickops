variable "region" {
  description = "Region for the state bucket and the CI role."
  type        = string
  default     = "ap-south-1"
}

variable "account_id" {
  description = "AWS account ID. Set in bootstrap.auto.tfvars (gitignored)."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "account_id must be a 12-digit AWS account ID."
  }
}

variable "github_owner" {
  description = "GitHub user or organisation that owns the repository."
  type        = string
}

variable "github_repo" {
  description = "GitHub repository name."
  type        = string
  default     = "clickops"
}
