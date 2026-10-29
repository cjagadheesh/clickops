resource "aws_route53_zone" "private" {
  name = "clickops.internal"

  vpc {
    vpc_id = aws_vpc.main.id
  }
}

resource "aws_route53_record" "app" {
  zone_id = aws_route53_zone.private.zone_id
  name    = "app.clickops.internal"
  type    = "A"
  ttl     = 300
  records = ["10.20.1.10"]
}

resource "aws_route53_record" "db" {
  zone_id = aws_route53_zone.private.zone_id
  name    = "db.clickops.internal"
  type    = "A"
  ttl     = 300
  records = ["10.20.1.20"]
}
