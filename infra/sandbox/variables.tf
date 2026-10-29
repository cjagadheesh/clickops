variable "region" {
  type    = string
  default = "ap-south-1"
}

variable "admin_cidr" {
  description = "Single /32 allowed to SSH to the admin security group."
  type        = string
  default     = "203.0.113.10/32"

  validation {
    condition     = can(regex("^([0-9]{1,3}\\.){3}[0-9]{1,3}/32$", var.admin_cidr)) && can(cidrhost(var.admin_cidr, 0))
    error_message = "admin_cidr must be a single IPv4 address in /32 form."
  }
}
