"""Write synthetic CloudTrail fixtures (as EventBridge events) under tests/fixtures/cloudtrail.

Real recordings come from scripts/make_fixture_events.sh and overwrite these files with
``_source: real``. Re-running this script never overwrites a file marked real.

    uv run python scripts/gen_synthetic_fixtures.py
"""

from __future__ import annotations

import json
import zlib
from pathlib import Path
from typing import Any

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "cloudtrail"
ACCOUNT = "111122223333"
SSO_ROLE = "AWSReservedSSO_AdminAccess_0123456789abcdef"
SG = "sg-0a1b2c3d4e5f60718"
INSTANCE = "i-0123456789abcdef0"
BUCKET = "clickops-sandbox-111122223333"
ZONE = "Z0123456789ABCDEFGHIJ"
ROLE = "clickops-sandbox-app"
POLICY_ARN = f"arn:aws:iam::{ACCOUNT}:policy/clickops-sandbox-extra"
FUNCTION = "clickops-sandbox-hello"


def identity(kind: str) -> dict[str, Any]:
    """User identity for an Identity Center person on the console or the CLI."""
    arn = f"arn:aws:sts::{ACCOUNT}:assumed-role/{SSO_ROLE}/asha@example.com"
    ctx: dict[str, Any] = {
        "attributes": {"creationDate": "2026-10-26T04:00:00Z", "mfaAuthenticated": "false"},
        "sessionIssuer": {
            "type": "Role",
            "principalId": "AROAEXAMPLEEXAMPLE",
            "arn": f"arn:aws:iam::{ACCOUNT}:role/aws-reserved/sso.amazonaws.com/{SSO_ROLE}",
            "accountId": ACCOUNT,
            "userName": SSO_ROLE,
        },
    }
    if kind == "console":
        ctx["attributes"]["sessionCredentialFromConsole"] = "true"
    return {
        "type": "AssumedRole",
        "principalId": "AROAEXAMPLEEXAMPLE:asha@example.com",
        "arn": arn,
        "accountId": ACCOUNT,
        "accessKeyId": "ASIAEXAMPLEEXAMPLE",
        "sessionContext": ctx,
    }


def make_event(
    *,
    service: str,
    source: str,
    name: str,
    region: str,
    request: dict[str, Any] | None,
    response: dict[str, Any] | None,
    actor: str = "cli",
    resources: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    console = actor == "console"
    event_id = f"11111111-2222-4333-8444-{zlib.crc32((name + actor).encode()):012d}"
    detail: dict[str, Any] = {
        "eventVersion": "1.10",
        "userIdentity": identity(actor),
        "eventTime": "2026-10-26T10:15:30Z",
        "eventSource": f"{service}.amazonaws.com",
        "eventName": name,
        "awsRegion": region,
        "sourceIPAddress": "203.0.113.25",
        "userAgent": "AWS Internal" if console else "aws-cli/2.17.0 Python/3.12.4 Linux/6.1",
        "requestParameters": request,
        "responseElements": response,
        "requestID": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        "eventID": event_id,
        "readOnly": False,
        "eventType": "AwsApiCall",
        "managementEvent": True,
        "recipientAccountId": ACCOUNT,
        "eventCategory": "Management",
    }
    return {
        "_source": "synthetic",
        "version": "0",
        "id": event_id,
        "detail-type": "AWS API Call via CloudTrail",
        "source": source,
        "account": ACCOUNT,
        "time": "2026-10-26T10:15:30Z",
        "region": region,
        "resources": resources or [],
        "detail": detail,
    }


def sg_rule_set(proto: str, port: int, cidr: str) -> dict[str, Any]:
    return {
        "items": [
            {
                "ipProtocol": proto,
                "fromPort": port,
                "toPort": port,
                "groupId": SG,
                "ipRanges": {"items": [{"cidrIp": cidr}]},
            }
        ]
    }


def build() -> list[tuple[str, str, dict[str, Any]]]:
    """Return (service dir, file stem, make_event kwargs)."""
    ap = "ap-south-1"
    ue = "us-east-1"
    inst = {"instancesSet": {"items": [{"instanceId": INSTANCE}]}}
    ingress = {"groupId": SG, "ipPermissions": sg_rule_set("tcp", 22, "0.0.0.0/0")}
    policy_doc = json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [{"Effect": "Allow", "Action": "s3:GetObject", "Resource": "*"}],
        }
    )
    trust_doc = json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": "sts:AssumeRole",
                    "Principal": {"Service": "lambda.amazonaws.com"},
                }
            ],
        }
    )
    s3 = dict(service="s3", source="aws.s3", region=ap)
    iam = dict(service="iam", source="aws.iam", region=ue)
    lam = dict(service="lambda", source="aws.lambda", region=ap)
    r53 = dict(service="route53", source="aws.route53", region=ue)
    c = dict(ec2=dict(service="ec2", source="aws.ec2", region=ap))["ec2"]

    def row(
        dirname: str,
        stem: str,
        base: dict[str, Any],
        name: str,
        req: Any,
        resp: Any,
        actor: str = "cli",
    ) -> tuple[str, str, dict[str, Any]]:
        return dirname, stem, dict(base, name=name, request=req, response=resp, actor=actor)

    return [
        row(
            "ec2",
            "CreateSecurityGroup",
            c,
            "CreateSecurityGroup",
            {"groupName": "scratch", "groupDescription": "scratch", "vpcId": "vpc-0abc1234"},
            {"requestId": "r", "_return": True, "groupId": SG},
        ),
        row(
            "ec2",
            "DeleteSecurityGroup",
            c,
            "DeleteSecurityGroup",
            {"groupId": SG},
            {"requestId": "r", "_return": True},
        ),
        row(
            "ec2",
            "AuthorizeSecurityGroupIngress",
            c,
            "AuthorizeSecurityGroupIngress",
            ingress,
            {"requestId": "r", "_return": True},
        ),
        row(
            "ec2",
            "AuthorizeSecurityGroupIngress.console",
            c,
            "AuthorizeSecurityGroupIngress",
            ingress,
            {"requestId": "r", "_return": True},
            "console",
        ),
        row(
            "ec2",
            "AuthorizeSecurityGroupEgress",
            c,
            "AuthorizeSecurityGroupEgress",
            {"groupId": SG, "ipPermissions": sg_rule_set("tcp", 8443, "10.0.0.0/8")},
            {"requestId": "r", "_return": True},
        ),
        row(
            "ec2",
            "RevokeSecurityGroupIngress",
            c,
            "RevokeSecurityGroupIngress",
            {"groupId": SG, "ipPermissions": sg_rule_set("tcp", 443, "0.0.0.0/0")},
            {"requestId": "r", "_return": True},
        ),
        row(
            "ec2",
            "RevokeSecurityGroupEgress",
            c,
            "RevokeSecurityGroupEgress",
            {"groupId": SG, "ipPermissions": sg_rule_set("-1", -1, "0.0.0.0/0")},
            {"requestId": "r", "_return": True},
        ),
        row(
            "ec2",
            "ModifySecurityGroupRules",
            c,
            "ModifySecurityGroupRules",
            {
                "groupId": SG,
                "ModifySecurityGroupRulesRequest": {
                    "SecurityGroupRule": {
                        "item": [
                            {
                                "securityGroupRuleId": "sgr-0123456789abcdef0",
                                "securityGroupRule": {
                                    "ipProtocol": "tcp",
                                    "fromPort": 22,
                                    "toPort": 22,
                                    "cidrIpv4": "0.0.0.0/0",
                                },
                            }
                        ]
                    }
                },
            },
            {"requestId": "r", "_return": True},
        ),
        row(
            "ec2",
            "RunInstances",
            c,
            "RunInstances",
            {
                "instancesSet": {"items": [{"imageId": "ami-0abc", "minCount": 1, "maxCount": 1}]},
                "instanceType": "t4g.nano",
            },
            {
                "requestId": "r",
                "instancesSet": {
                    "items": [{"instanceId": INSTANCE}, {"instanceId": "i-0fedcba9876543210"}]
                },
            },
        ),
        row(
            "ec2",
            "TerminateInstances",
            c,
            "TerminateInstances",
            inst,
            {"requestId": "r", "instancesSet": {"items": [{"instanceId": INSTANCE}]}},
        ),
        row(
            "ec2",
            "ModifyInstanceAttribute",
            c,
            "ModifyInstanceAttribute",
            {"instanceId": INSTANCE, "instanceType": {"value": "t4g.small"}},
            {"requestId": "r", "_return": True},
        ),
        row("ec2", "StartInstances", c, "StartInstances", inst, {"requestId": "r"}),
        row("ec2", "StopInstances", c, "StopInstances", inst, {"requestId": "r"}),
        row(
            "iam",
            "CreateRole",
            iam,
            "CreateRole",
            {"roleName": ROLE, "assumeRolePolicyDocument": trust_doc},
            {"role": {"roleName": ROLE, "arn": f"arn:aws:iam::{ACCOUNT}:role/{ROLE}"}},
        ),
        row("iam", "DeleteRole", iam, "DeleteRole", {"roleName": ROLE}, None),
        row(
            "iam",
            "UpdateAssumeRolePolicy",
            iam,
            "UpdateAssumeRolePolicy",
            {"roleName": ROLE, "policyDocument": trust_doc},
            None,
        ),
        row(
            "iam",
            "PutRolePolicy",
            iam,
            "PutRolePolicy",
            {"roleName": ROLE, "policyName": "read-sandbox-bucket", "policyDocument": policy_doc},
            None,
        ),
        row(
            "iam",
            "DeleteRolePolicy",
            iam,
            "DeleteRolePolicy",
            {"roleName": ROLE, "policyName": "read-sandbox-bucket"},
            None,
        ),
        row(
            "iam",
            "AttachRolePolicy",
            iam,
            "AttachRolePolicy",
            {"roleName": ROLE, "policyArn": "arn:aws:iam::aws:policy/AmazonS3FullAccess"},
            None,
        ),
        row(
            "iam",
            "AttachRolePolicy.console",
            iam,
            "AttachRolePolicy",
            {"roleName": ROLE, "policyArn": "arn:aws:iam::aws:policy/AmazonS3FullAccess"},
            None,
            "console",
        ),
        row(
            "iam",
            "DetachRolePolicy",
            iam,
            "DetachRolePolicy",
            {"roleName": ROLE, "policyArn": "arn:aws:iam::aws:policy/AmazonS3FullAccess"},
            None,
        ),
        row(
            "iam",
            "CreatePolicy",
            iam,
            "CreatePolicy",
            {"policyName": "clickops-sandbox-extra", "policyDocument": policy_doc},
            {"policy": {"policyName": "clickops-sandbox-extra", "arn": POLICY_ARN}},
        ),
        row(
            "iam",
            "CreatePolicyVersion",
            iam,
            "CreatePolicyVersion",
            {"policyArn": POLICY_ARN, "policyDocument": policy_doc, "setAsDefault": True},
            {"policyVersion": {"versionId": "v2", "isDefaultVersion": True}},
        ),
        row("s3", "CreateBucket", s3, "CreateBucket", {"bucketName": BUCKET, "Host": "s3"}, None),
        row("s3", "DeleteBucket", s3, "DeleteBucket", {"bucketName": BUCKET}, None),
        row(
            "s3",
            "PutBucketPolicy",
            s3,
            "PutBucketPolicy",
            {"bucketName": BUCKET, "bucketPolicy": json.loads(policy_doc)},
            None,
        ),
        row("s3", "DeleteBucketPolicy", s3, "DeleteBucketPolicy", {"bucketName": BUCKET}, None),
        row(
            "s3",
            "PutBucketPublicAccessBlock",
            s3,
            "PutBucketPublicAccessBlock",
            {
                "bucketName": BUCKET,
                "PublicAccessBlockConfiguration": {
                    "BlockPublicAcls": False,
                    "IgnorePublicAcls": False,
                    "BlockPublicPolicy": False,
                    "RestrictPublicBuckets": False,
                },
            },
            None,
        ),
        row(
            "s3",
            "PutBucketPublicAccessBlock.console",
            s3,
            "PutBucketPublicAccessBlock",
            {
                "bucketName": BUCKET,
                "PublicAccessBlockConfiguration": {
                    "BlockPublicAcls": False,
                    "IgnorePublicAcls": False,
                    "BlockPublicPolicy": False,
                    "RestrictPublicBuckets": False,
                },
            },
            None,
            "console",
        ),
        row(
            "s3",
            "DeleteBucketPublicAccessBlock",
            s3,
            "DeleteBucketPublicAccessBlock",
            {"bucketName": BUCKET},
            None,
        ),
        row(
            "s3",
            "PutBucketVersioning",
            s3,
            "PutBucketVersioning",
            {"bucketName": BUCKET, "VersioningConfiguration": {"Status": "Suspended"}},
            None,
        ),
        row(
            "s3",
            "PutBucketEncryption",
            s3,
            "PutBucketEncryption",
            {
                "bucketName": BUCKET,
                "ServerSideEncryptionConfiguration": {
                    "Rule": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "aws:kms"}}]
                },
            },
            None,
        ),
        row(
            "lambda",
            "CreateFunction20150331",
            lam,
            "CreateFunction20150331",
            {
                "functionName": FUNCTION,
                "runtime": "python3.12",
                "handler": "hello.handler",
                "role": f"arn:aws:iam::{ACCOUNT}:role/{ROLE}",
            },
            {"functionName": FUNCTION, "runtime": "python3.12", "timeout": 10},
        ),
        row(
            "lambda",
            "DeleteFunction20150331",
            lam,
            "DeleteFunction20150331",
            {"functionName": FUNCTION},
            None,
        ),
        row(
            "lambda",
            "UpdateFunctionConfiguration20150331v2",
            lam,
            "UpdateFunctionConfiguration20150331v2",
            {"functionName": FUNCTION, "timeout": 60},
            {"functionName": FUNCTION, "timeout": 60, "runtime": "python3.12"},
        ),
        row(
            "lambda",
            "UpdateFunctionCode20150331v2",
            lam,
            "UpdateFunctionCode20150331v2",
            {"functionName": FUNCTION, "publish": False},
            {"functionName": FUNCTION, "codeSha256": "abc123"},
        ),
        row(
            "lambda",
            "AddPermission20150331v2",
            lam,
            "AddPermission20150331v2",
            {
                "functionName": FUNCTION,
                "statementId": "public",
                "action": "lambda:InvokeFunction",
                "principal": "*",
            },
            {"statement": "{}"},
        ),
        row(
            "route53",
            "ChangeResourceRecordSets",
            r53,
            "ChangeResourceRecordSets",
            {
                "hostedZoneId": ZONE,
                "changeBatch": {
                    "changes": [
                        {
                            "action": "UPSERT",
                            "resourceRecordSet": {
                                "name": "app.clickops.internal.",
                                "type": "A",
                                "tTL": 300,
                                "resourceRecords": [{"value": "10.20.1.99"}],
                            },
                        },
                        {
                            "action": "DELETE",
                            "resourceRecordSet": {
                                "name": "db.clickops.internal.",
                                "type": "A",
                                "tTL": 300,
                                "resourceRecords": [{"value": "10.20.1.20"}],
                            },
                        },
                    ]
                },
            },
            {"changeInfo": {"id": "/change/C0123456789ABC", "status": "PENDING"}},
        ),
        row(
            "route53",
            "CreateHostedZone",
            r53,
            "CreateHostedZone",
            {"name": "scratch.internal.", "hostedZoneConfig": {"privateZone": True}},
            {"hostedZone": {"id": f"/hostedzone/{ZONE}", "name": "scratch.internal."}},
        ),
        row(
            "route53",
            "DeleteHostedZone",
            r53,
            "DeleteHostedZone",
            {"id": ZONE},
            {"changeInfo": {"id": "/change/C0123456789ABD", "status": "PENDING"}},
        ),
    ]


def main() -> None:
    for dirname, stem, kwargs in build():
        path = OUT / dirname / f"{stem}.json"
        if path.exists() and json.loads(path.read_text()).get("_source") == "real":
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        service = {
            "ec2": "ec2",
            "iam": "iam",
            "s3": "s3",
            "lambda": "lambda",
            "route53": "route53",
        }[dirname]
        kwargs = dict(kwargs, service=service)
        path.write_text(json.dumps(make_event(**kwargs), indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
