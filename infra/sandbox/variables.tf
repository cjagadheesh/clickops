variable "region" {
  type    = string
  default = "ap-south-1"
}

variable "admin_cidr" {
  description = "Single /32 allowed to SSH to the admin security group."
  type        = string
  default     = "203.0.113.10/32"

  validation {
    condition     = can(cidrhost(var.admin_cidr, 0)) && endswith(var.admin_cidr, "/32")
    error_message = "admin_cidr must be a single IPv4 address in /32 form."
  }
}
