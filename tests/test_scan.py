import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3
import pytest
from helpers_state import index_of, resource
from moto import mock_aws
from typer.testing import CliRunner

from clickops import scan as scan_mod
from clickops import store
from clickops.cli import app
from clickops.state import StateIndex

TRUST = json.dumps(
    {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
)
POLICY = json.dumps(
    {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Action": "s3:GetObject", "Resource": "*"}],
    }
)
REGION = "ap-south-1"


@pytest.fixture
def aws(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    with mock_aws():
        yield


def ids(found: list[scan_mod.ShadowResource], kind: str) -> list[str]:
    return [r.id for r in found if r.type == kind]


def run(index: StateIndex | None = None) -> list[scan_mod.ShadowResource]:
    return scan_mod.scan(index or index_of(), REGION)


# --- security groups ---------------------------------------------------------------------------


def test_default_security_groups_are_excluded_and_managed_ones_are_not_reported(aws) -> None:  # type: ignore[no-untyped-def]
    ec2 = boto3.client("ec2", region_name=REGION)
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]  # also gets a default group
    managed = ec2.create_security_group(GroupName="web", Description="d", VpcId=vpc)["GroupId"]
    shadow = ec2.create_security_group(GroupName="scratch", Description="d", VpcId=vpc)["GroupId"]
    index = index_of(resource("aws_security_group", "web", id=managed))
    found = ids(run(index), "sg")
    assert found == [shadow]
    assert [r.name for r in run(index) if r.type == "sg"] == ["scratch"]


# --- IAM ---------------------------------------------------------------------------------------


def test_service_linked_and_sso_roles_are_excluded(aws) -> None:  # type: ignore[no-untyped-def]
    iam = boto3.client("iam", region_name="us-east-1")
    iam.create_role(
        RoleName="AWSServiceRoleForAutoScaling",
        Path="/aws-service-role/x.amazonaws.com/",
        AssumeRolePolicyDocument=TRUST,
    )
    iam.create_role(
        RoleName="AWSReservedSSO_Admin_0123",
        Path="/aws-reserved/sso.amazonaws.com/",
        AssumeRolePolicyDocument=TRUST,
    )
    iam.create_role(RoleName="managed", AssumeRolePolicyDocument=TRUST)
    iam.create_role(RoleName="clicked", AssumeRolePolicyDocument=TRUST)
    index = index_of(resource("aws_iam_role", "m", id="managed", name="managed"))
    assert ids(run(index), "iam-role") == ["clicked"]


def test_only_customer_managed_policies_are_considered(aws, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    iam = boto3.client("iam", region_name="us-east-1")
    arn = iam.create_policy(PolicyName="mine", PolicyDocument=POLICY)["Policy"]["Arn"]
    managed = iam.create_policy(PolicyName="coded", PolicyDocument=POLICY)["Policy"]["Arn"]
    index = index_of(resource("aws_iam_policy", "c", id=managed, arn=managed))
    found = run(index)
    assert ids(found, "iam-policy") == [arn]
    assert not any(r.id.startswith("arn:aws:iam::aws:") for r in found)


def test_aws_managed_policies_are_excluded_even_when_listed_by_the_account(
    aws, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("MOTO_IAM_LOAD_MANAGED_POLICIES", "true")
    iam = boto3.client("iam", region_name="us-east-1")
    assert any(p["Arn"].startswith("arn:aws:iam::aws:") for p in iam.list_policies()["Policies"])
    assert ids(run(), "iam-policy") == []


# --- S3 ----------------------------------------------------------------------------------------


def test_buckets_in_other_regions_are_excluded(aws) -> None:  # type: ignore[no-untyped-def]
    s3 = boto3.client("s3", region_name=REGION)
    s3.create_bucket(Bucket="here", CreateBucketConfiguration={"LocationConstraint": REGION})
    s3.create_bucket(
        Bucket="managed-here", CreateBucketConfiguration={"LocationConstraint": REGION}
    )
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="elsewhere")
    boto3.client("s3", region_name="eu-west-1").create_bucket(
        Bucket="europe", CreateBucketConfiguration={"LocationConstraint": "eu-west-1"}
    )
    index = index_of(resource("aws_s3_bucket", "m", id="managed-here", bucket="managed-here"))
    found = [r for r in run(index) if r.type == "s3"]
    assert [r.id for r in found] == ["here"]
    assert found[0].created is not None


# --- EC2 ---------------------------------------------------------------------------------------


def test_terminated_instances_are_excluded(aws) -> None:  # type: ignore[no-untyped-def]
    ec2 = boto3.client("ec2", region_name=REGION)

    def launch(name: str) -> str:
        return ec2.run_instances(
            ImageId="ami-12c6146b",
            MinCount=1,
            MaxCount=1,
            InstanceType="t4g.nano",
            TagSpecifications=[
                {"ResourceType": "instance", "Tags": [{"Key": "Name", "Value": name}]}
            ],
        )["Instances"][0]["InstanceId"]

    managed, gone, shadow = launch("coded"), launch("old"), launch("scratch")
    ec2.terminate_instances(InstanceIds=[gone])
    index = index_of(resource("aws_instance", "m", id=managed))
    found = [r for r in run(index) if r.type == "ec2"]
    assert [r.id for r in found] == [shadow]
    assert found[0].name == "scratch" and found[0].created is not None


# --- Lambda ------------------------------------------------------------------------------------


def test_lambda_functions_without_state_are_reported(aws) -> None:  # type: ignore[no-untyped-def]
    iam = boto3.client("iam", region_name="us-east-1")
    role = iam.create_role(RoleName="r", AssumeRolePolicyDocument=TRUST)["Role"]["Arn"]
    lam = boto3.client("lambda", region_name=REGION)
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("h.py", "def h(e, c):\n    return 1\n")
    for name in ("coded", "clicked"):
        lam.create_function(
            FunctionName=name,
            Runtime="python3.12",
            Role=role,
            Handler="h.h",
            Code={"ZipFile": buf.getvalue()},
        )
    index = index_of(resource("aws_lambda_function", "c", id="coded", function_name="coded"))
    assert ids(run(index), "lambda") == ["clicked"]


# --- Route 53 ----------------------------------------------------------------------------------


def _zone(name: str) -> str:
    r53 = boto3.client("route53", region_name="us-east-1")
    return r53.create_hosted_zone(Name=name, CallerReference=name)["HostedZone"]["Id"].rsplit(
        "/", 1
    )[-1]


def _record(zone: str, name: str, value: str, rtype: str = "A") -> None:
    boto3.client("route53", region_name="us-east-1").change_resource_record_sets(
        HostedZoneId=zone,
        ChangeBatch={
            "Changes": [
                {
                    "Action": "UPSERT",
                    "ResourceRecordSet": {
                        "Name": name,
                        "Type": rtype,
                        "TTL": 60,
                        "ResourceRecords": [{"Value": value}],
                    },
                }
            ]
        },
    )


def test_ns_and_soa_records_are_excluded_and_managed_records_are_not_reported(aws) -> None:  # type: ignore[no-untyped-def]
    zone = _zone("clickops.internal")
    _record(zone, "app.clickops.internal", "10.0.0.1")
    _record(zone, "scratch.clickops.internal", "10.0.0.2")
    index = index_of(
        resource("aws_route53_zone", "z", id=zone, zone_id=zone),
        resource("aws_route53_record", "app", id=f"{zone}_app.clickops.internal_A"),
    )
    found = run(index)
    assert ids(found, "route53-record") == [f"{zone}_scratch.clickops.internal_A"]
    assert not any(r.id.endswith(("_NS", "_SOA")) for r in found)


def test_an_unmanaged_zone_is_reported_without_its_records(aws) -> None:  # type: ignore[no-untyped-def]
    zone = _zone("scratch.internal")
    _record(zone, "x.scratch.internal", "10.0.0.3")
    found = run()
    assert ids(found, "route53-zone") == [zone]
    assert [r.name for r in found if r.type == "route53-zone"] == ["scratch.internal"]
    assert ids(found, "route53-record") == []


# --- creator, ordering and output --------------------------------------------------------------


def make_table() -> Any:
    boto3.client("dynamodb", region_name=REGION).create_table(**store.TABLE_DEFINITION)
    return boto3.resource("dynamodb", region_name=REGION).Table(store.TABLE_NAME)


def test_creator_comes_from_the_event_store(aws) -> None:  # type: ignore[no-untyped-def]
    boto3.client("s3", region_name=REGION).create_bucket(
        Bucket="clicked", CreateBucketConfiguration={"LocationConstraint": REGION}
    )
    boto3.client("s3", region_name=REGION).create_bucket(
        Bucket="unknown", CreateBucketConfiguration={"LocationConstraint": REGION}
    )
    table = make_table()
    when = datetime(2026, 10, 26, 10, tzinfo=UTC)
    store.put_event(
        table,
        store.build_item(
            resource_key="s3#clicked",
            event_id="e1",
            when=when,
            fields={"outcome": "shadow-create", "actor_name": "asha@example.com"},
        ),
    )
    found = {r.id: r for r in scan_mod.scan(index_of(), REGION, table)}
    assert found["clicked"].creator == "asha@example.com"
    assert found["unknown"].creator is None


def test_missing_event_table_does_not_break_the_scan(aws) -> None:  # type: ignore[no-untyped-def]
    boto3.client("s3", region_name=REGION).create_bucket(
        Bucket="clicked", CreateBucketConfiguration={"LocationConstraint": REGION}
    )
    table = boto3.resource("dynamodb", region_name=REGION).Table("does-not-exist")
    assert scan_mod.scan(index_of(), REGION, table)[0].creator is None


def test_results_are_sorted_and_serialisable(aws) -> None:  # type: ignore[no-untyped-def]
    s3 = boto3.client("s3", region_name=REGION)
    for name in ("b-bucket", "a-bucket"):
        s3.create_bucket(Bucket=name, CreateBucketConfiguration={"LocationConstraint": REGION})
    boto3.client("iam", region_name="us-east-1").create_role(
        RoleName="r", AssumeRolePolicyDocument=TRUST
    )
    found = run()
    assert [(r.type, r.id) for r in found] == [
        ("iam-role", "r"),
        ("s3", "a-bucket"),
        ("s3", "b-bucket"),
    ]
    assert json.dumps([r.to_json() for r in found])


def test_everything_in_state_means_nothing_is_reported(aws) -> None:  # type: ignore[no-untyped-def]
    boto3.client("s3", region_name=REGION).create_bucket(
        Bucket="coded", CreateBucketConfiguration={"LocationConstraint": REGION}
    )
    assert run(index_of(resource("aws_s3_bucket", "c", id="coded"))) == []


# --- CLI ---------------------------------------------------------------------------------------


@pytest.fixture
def cli_setup(aws, tmp_path: Path) -> Path:  # type: ignore[no-untyped-def]
    s3 = boto3.client("s3", region_name=REGION)
    s3.create_bucket(Bucket="tfstate", CreateBucketConfiguration={"LocationConstraint": REGION})
    s3.create_bucket(Bucket="coded", CreateBucketConfiguration={"LocationConstraint": REGION})
    s3.create_bucket(Bucket="clicked", CreateBucketConfiguration={"LocationConstraint": REGION})
    state = {
        "version": 4,
        "resources": [
            {
                "mode": "managed",
                "type": "aws_s3_bucket",
                "name": "c",
                "instances": [{"attributes": {"id": "coded"}}],
            },
            {
                "mode": "managed",
                "type": "aws_s3_bucket",
                "name": "t",
                "instances": [{"attributes": {"id": "tfstate"}}],
            },
        ],
    }
    s3.put_object(Bucket="tfstate", Key="s.tfstate", Body=json.dumps(state))
    make_table()
    config = tmp_path / "clickops.yaml"
    config.write_text("state_locations:\n  - bucket: tfstate\n    key: s.tfstate\n")
    return config


def test_scan_command_prints_a_table(cli_setup: Path) -> None:
    result = CliRunner().invoke(app, ["scan", "--config", str(cli_setup)], env={"COLUMNS": "160"})
    assert result.exit_code == 0, result.output
    assert "clicked" in result.output and "coded" not in result.output.replace("tfstate", "")


def test_scan_command_json(cli_setup: Path) -> None:
    result = CliRunner().invoke(app, ["scan", "--config", str(cli_setup), "--json"])
    assert result.exit_code == 0, result.output
    assert [r["id"] for r in json.loads(result.output)] == ["clicked"]


def test_scan_command_reports_nothing_when_everything_is_managed(cli_setup: Path) -> None:
    boto3.client("s3", region_name=REGION).delete_bucket(Bucket="clicked")
    result = CliRunner().invoke(app, ["scan", "--config", str(cli_setup)])
    assert result.exit_code == 0 and "No shadow resources" in result.output


def test_scan_command_fails_clearly_on_bad_config(aws, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    result = CliRunner().invoke(app, ["scan", "--config", str(tmp_path / "missing.yaml")])
    assert result.exit_code == 2
