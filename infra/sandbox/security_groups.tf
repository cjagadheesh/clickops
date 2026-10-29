resource "aws_security_group" "web" {
  name        = "web"
  description = "Public HTTPS"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "web" }
}

resource "aws_security_group" "admin" {
  name        = "admin"
  description = "SSH from one admin address"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "admin" }
}

resource "aws_vpc_security_group_ingress_rule" "web_https" {
  security_group_id = aws_security_group.web.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_ingress_rule" "admin_ssh" {
  security_group_id = aws_security_group.admin.id
  cidr_ipv4         = var.admin_cidr
  ip_protocol       = "tcp"
  from_port         = 22
  to_port           = 22
}
