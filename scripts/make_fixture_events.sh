#!/usr/bin/env bash
# Make each watched write call once against the sandbox, then record the CloudTrail events as
# fixtures. Needs the clickops-admin profile and the human's approval: it creates and deletes
# scratch resources and changes sandbox resources. Undo the sandbox changes afterwards with
# `terraform apply` in infra/sandbox.
#
# Not recorded for real (kept synthetic): RunInstances, TerminateInstances, CreateHostedZone,
# DeleteHostedZone (cost and safety).
#
#   CONFIRM=yes AWS_PROFILE=clickops-admin scripts/make_fixture_events.sh
set -euo pipefail

if [ "${CONFIRM:-}" != "yes" ]; then
  echo "This changes real AWS resources. Re-run with CONFIRM=yes after approval." >&2
  exit 1
fi

REGION=ap-south-1
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
START=$(date -u +%Y-%m-%dT%H:%M:%SZ)
SUFFIX=$(date +%s)
TAGS="Key=project,Value=clickops Key=owner,Value=agent"

echo "== sandbox lookups"
VPC=$(aws ec2 describe-vpcs --region $REGION --filters Name=tag:Name,Values=clickops-sandbox \
  --query 'Vpcs[0].VpcId' --output text)
INSTANCE=$(aws ec2 describe-instances --region $REGION \
  --filters Name=tag:Name,Values=clickops-sandbox Name=instance-state-name,Values=stopped \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)
ZONE=$(aws route53 list-hosted-zones-by-name --dns-name clickops.internal \
  --query 'HostedZones[0].Id' --output text | sed 's#/hostedzone/##')

echo "== security groups"
SG=$(aws ec2 create-security-group --region $REGION --vpc-id "$VPC" \
  --group-name "scratch-$SUFFIX" --description scratch \
  --tag-specifications "ResourceType=security-group,Tags=[{Key=project,Value=clickops},{Key=owner,Value=agent}]" \
  --query GroupId --output text)
aws ec2 authorize-security-group-ingress --region $REGION --group-id "$SG" \
  --protocol tcp --port 8443 --cidr 10.0.0.0/8 > /dev/null
RULE=$(aws ec2 describe-security-group-rules --region $REGION --filters Name=group-id,Values="$SG" \
  --query 'SecurityGroupRules[?!IsEgress]|[0].SecurityGroupRuleId' --output text)
aws ec2 modify-security-group-rules --region $REGION --group-id "$SG" \
  --security-group-rules "SecurityGroupRuleId=$RULE,SecurityGroupRule={IpProtocol=tcp,FromPort=8443,ToPort=8443,CidrIpv4=10.1.0.0/16}" > /dev/null
aws ec2 revoke-security-group-ingress --region $REGION --group-id "$SG" \
  --protocol tcp --port 8443 --cidr 10.1.0.0/16 > /dev/null
aws ec2 authorize-security-group-egress --region $REGION --group-id "$SG" \
  --ip-permissions IpProtocol=tcp,FromPort=8443,ToPort=8443,IpRanges='[{CidrIp=10.0.0.0/8}]' > /dev/null
aws ec2 revoke-security-group-egress --region $REGION --group-id "$SG" \
  --ip-permissions IpProtocol=tcp,FromPort=8443,ToPort=8443,IpRanges='[{CidrIp=10.0.0.0/8}]' > /dev/null
aws ec2 delete-security-group --region $REGION --group-id "$SG"

echo "== instance (sandbox instance is started and stopped again)"
aws ec2 start-instances --region $REGION --instance-ids "$INSTANCE" > /dev/null
aws ec2 wait instance-running --region $REGION --instance-ids "$INSTANCE"
aws ec2 stop-instances --region $REGION --instance-ids "$INSTANCE" > /dev/null
aws ec2 wait instance-stopped --region $REGION --instance-ids "$INSTANCE"
aws ec2 modify-instance-attribute --region $REGION --instance-id "$INSTANCE" \
  --no-disable-api-termination

echo "== iam (scratch role and policy)"
ROLE="clickops-scratch-$SUFFIX"
TRUST='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
DOC='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"s3:ListAllMyBuckets","Resource":"*"}]}'
aws iam create-role --role-name "$ROLE" --assume-role-policy-document "$TRUST" --tags $TAGS > /dev/null
aws iam update-assume-role-policy --role-name "$ROLE" --policy-document "$TRUST"
aws iam put-role-policy --role-name "$ROLE" --policy-name scratch --policy-document "$DOC"
aws iam delete-role-policy --role-name "$ROLE" --policy-name scratch
POLICY_ARN=$(aws iam create-policy --policy-name "clickops-scratch-$SUFFIX" \
  --policy-document "$DOC" --query Policy.Arn --output text)
aws iam create-policy-version --policy-arn "$POLICY_ARN" --policy-document "$DOC" --set-as-default > /dev/null
aws iam attach-role-policy --role-name "$ROLE" --policy-arn "$POLICY_ARN"
aws iam detach-role-policy --role-name "$ROLE" --policy-arn "$POLICY_ARN"
aws iam delete-policy-version --policy-arn "$POLICY_ARN" --version-id v1
aws iam delete-policy --policy-arn "$POLICY_ARN"
aws iam delete-role --role-name "$ROLE"

echo "== s3 (scratch bucket)"
BUCKET="clickops-scratch-$ACCOUNT-$SUFFIX"
aws s3api create-bucket --bucket "$BUCKET" --region $REGION \
  --create-bucket-configuration LocationConstraint=$REGION > /dev/null
aws s3api put-bucket-versioning --bucket "$BUCKET" --versioning-configuration Status=Enabled
aws s3api put-bucket-encryption --bucket "$BUCKET" --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
  BlockPublicAcls=false,IgnorePublicAcls=false,BlockPublicPolicy=false,RestrictPublicBuckets=false
aws s3api delete-public-access-block --bucket "$BUCKET"
aws s3api put-bucket-policy --bucket "$BUCKET" --policy \
  "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Deny\",\"Principal\":\"*\",\"Action\":\"s3:*\",\"Resource\":[\"arn:aws:s3:::$BUCKET\",\"arn:aws:s3:::$BUCKET/*\"],\"Condition\":{\"Bool\":{\"aws:SecureTransport\":\"false\"}}}]}"
aws s3api delete-bucket-policy --bucket "$BUCKET"
aws s3api delete-bucket --bucket "$BUCKET" --region $REGION

echo "== lambda (sandbox function, reverted by terraform apply)"
FN=clickops-sandbox-hello
aws lambda update-function-configuration --region $REGION --function-name $FN --timeout 20 > /dev/null
aws lambda wait function-updated --region $REGION --function-name $FN
TMP=$(mktemp -d)
printf 'def handler(event, context):\n    return {"statusCode": 200}\n' > "$TMP/hello.py"
(cd "$TMP" && python3 -c "import zipfile; zipfile.ZipFile('hello.zip','w').write('hello.py')")
aws lambda update-function-code --region $REGION --function-name $FN --zip-file "fileb://$TMP/hello.zip" > /dev/null
aws lambda wait function-updated --region $REGION --function-name $FN
aws lambda add-permission --region $REGION --function-name $FN --statement-id scratch \
  --action lambda:InvokeFunction --principal "$ACCOUNT" > /dev/null
aws lambda remove-permission --region $REGION --function-name $FN --statement-id scratch
rm -rf "$TMP"

echo "== route53 (sandbox record, reverted by terraform apply)"
aws route53 change-resource-record-sets --hosted-zone-id "$ZONE" --change-batch \
  '{"Changes":[{"Action":"UPSERT","ResourceRecordSet":{"Name":"app.clickops.internal","Type":"A","TTL":300,"ResourceRecords":[{"Value":"10.20.1.99"}]}}]}' > /dev/null

echo "== waiting for CloudTrail event history (about 5 minutes)"
sleep 300
uv run python scripts/fetch_fixtures.py --since "$START"
echo "Done. Now run terraform apply in infra/sandbox to undo the sandbox changes."
