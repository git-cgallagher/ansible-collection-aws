# -*- coding: utf-8 -*-
# MIT License (see LICENSE or https://opensource.org/licenses/MIT)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

boto3 = pytest.importorskip("boto3")
moto = pytest.importorskip("moto")

from ansible.errors import AnsibleLookupError
from ansible.plugins.loader import lookup_loader

from ansible_collections.git_cgallagher.aws.plugins.lookup import ssm_parameter as plugin

REGION = "us-east-1"
SOURCE_ACCOUNT = "123456789012"  # moto's default account for the base credentials
TARGET_ACCOUNT = "111111111111"
ROLE = "ParamReader"


@pytest.fixture(autouse=True)
def aws_env(monkeypatch):
    for var in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_REGION", "AWS_DEFAULT_REGION"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    plugin._CRED_CACHE.clear()
    with moto.mock_aws():
        yield


@pytest.fixture
def lookup():
    return lookup_loader.get("git_cgallagher.aws.ssm_parameter")


def _target_ssm():
    """SSM client acting inside TARGET_ACCOUNT, used to seed test data."""
    sts = boto3.client("sts", region_name=REGION)
    creds = sts.assume_role(
        RoleArn="arn:aws:iam::%s:role/seed" % TARGET_ACCOUNT,
        RoleSessionName="seed",
    )["Credentials"]
    return boto3.client(
        "ssm",
        region_name=REGION,
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
    )


# ---- plain lookups (no role) ---------------------------------------------------


def test_simple_lookup(lookup):
    boto3.client("ssm", region_name=REGION).put_parameter(Name="/app/name", Value="hello", Type="String")
    assert lookup.run(["/app/name"], {}, region=REGION) == ["hello"]


def test_region_from_env(lookup, monkeypatch):
    monkeypatch.setenv("AWS_REGION", REGION)
    boto3.client("ssm", region_name=REGION).put_parameter(Name="/app/name", Value="hello", Type="String")
    assert lookup.run(["/app/name"], {}) == ["hello"]


def test_secure_string_decrypt(lookup):
    boto3.client("ssm", region_name=REGION).put_parameter(Name="/app/pw", Value="s3cret", Type="SecureString")
    assert lookup.run(["/app/pw"], {}, region=REGION) == ["s3cret"]
    assert lookup.run(["/app/pw"], {}, region=REGION, decrypt=False) != ["s3cret"]


def test_multiple_terms(lookup):
    ssm = boto3.client("ssm", region_name=REGION)
    ssm.put_parameter(Name="/a", Value="1", Type="String")
    ssm.put_parameter(Name="/b", Value="2", Type="String")
    assert lookup.run(["/a", "/b"], {}, region=REGION) == ["1", "2"]


# ---- role assumption -----------------------------------------------------------


def test_account_and_role_name_reads_other_account(lookup):
    _target_ssm().put_parameter(Name="/x/secret", Value="from-target", Type="SecureString")

    # Not visible to the base credentials' own account...
    with pytest.raises(AnsibleLookupError, match="not found"):
        lookup.run(["/x/secret"], {}, region=REGION)

    # ...but visible once the role in the target account is assumed.
    result = lookup.run(["/x/secret"], {}, region=REGION, account=TARGET_ACCOUNT, role_name=ROLE)
    assert result == ["from-target"]


def test_role_arn_reads_other_account(lookup):
    _target_ssm().put_parameter(Name="/x/secret", Value="from-target", Type="String")
    arn = "arn:aws:iam::%s:role/%s" % (TARGET_ACCOUNT, ROLE)
    assert lookup.run(["/x/secret"], {}, region=REGION, role_arn=arn) == ["from-target"]


def test_options_from_kwargs_aliases(lookup):
    _target_ssm().put_parameter(Name="/x/secret", Value="from-target", Type="String")
    result = lookup.run(["/x/secret"], {}, aws_region=REGION, account_id=TARGET_ACCOUNT, role_name=ROLE)
    assert result == ["from-target"]


def test_assume_role_call_parameters(lookup):
    captured = {}
    real_client = boto3.session.Session.client

    def spy_client(self, service, **kwargs):
        client = real_client(self, service, **kwargs)
        if service == "sts":
            real_assume = client.assume_role

            def assume_role(**params):
                captured.update(params)
                return real_assume(**params)

            client.assume_role = assume_role
        return client

    _target_ssm().put_parameter(Name="/p", Value="v", Type="String")
    with patch.object(boto3.session.Session, "client", spy_client):
        lookup.run(
            ["/p"],
            {},
            region=REGION,
            account=TARGET_ACCOUNT,
            role_name="/service-role/" + ROLE,
            external_id="ext-123",
            role_session_name="my-session",
            duration_seconds=1800,
        )

    assert captured == {
        "RoleArn": "arn:aws:iam::%s:role/service-role/%s" % (TARGET_ACCOUNT, ROLE),
        "RoleSessionName": "my-session",
        "DurationSeconds": 1800,
        "ExternalId": "ext-123",
    }


def test_assumed_credentials_are_cached(lookup):
    _target_ssm().put_parameter(Name="/p", Value="v", Type="String")
    calls = []
    real_client = boto3.session.Session.client

    def spy_client(self, service, **kwargs):
        if service == "sts":
            calls.append(service)
        return real_client(self, service, **kwargs)

    with patch.object(boto3.session.Session, "client", spy_client):
        for dummy in range(3):
            lookup.run(["/p"], {}, region=REGION, account=TARGET_ACCOUNT, role_name=ROLE)
    assert calls == ["sts"]


def test_expiring_credentials_are_refreshed(lookup):
    _target_ssm().put_parameter(Name="/p", Value="v", Type="String")
    lookup.run(["/p"], {}, region=REGION, account=TARGET_ACCOUNT, role_name=ROLE)
    (key,) = list(plugin._CRED_CACHE)
    stale = plugin._CRED_CACHE[key]
    stale["Expiration"] = datetime.now(timezone.utc) + timedelta(minutes=1)

    lookup.run(["/p"], {}, region=REGION, account=TARGET_ACCOUNT, role_name=ROLE)
    assert plugin._CRED_CACHE[key]["Expiration"] > datetime.now(timezone.utc) + timedelta(minutes=10)


def test_assume_role_failure_is_reported(lookup):
    err = plugin.botocore.exceptions.ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "not authorized to perform sts:AssumeRole"}}, "AssumeRole"
    )
    fake_sts = MagicMock()
    fake_sts.assume_role.side_effect = err
    with patch.object(plugin.LookupModule, "_make_client", return_value=fake_sts):
        with pytest.raises(AnsibleLookupError, match="Failed to assume role arn:aws:iam::111111111111:role/ParamReader"):
            lookup.run(["/p"], {}, region=REGION, account=TARGET_ACCOUNT, role_name=ROLE)


# ---- partitions ----------------------------------------------------------------


@pytest.mark.parametrize(
    "region, expected",
    [
        ("us-east-1", "aws"),
        ("eu-west-2", "aws"),
        ("cn-north-1", "aws-cn"),
        ("us-gov-west-1", "aws-us-gov"),
        ("us-iso-east-1", "aws-iso"),
        ("us-isob-east-1", "aws-iso-b"),
        (None, "aws"),
    ],
)
def test_partition_for_region(region, expected):
    assert plugin._partition_for_region(region) == expected


def test_role_arn_uses_partition(lookup):
    lookup.set_options(direct={"account": TARGET_ACCOUNT, "role_name": ROLE, "region": "us-gov-west-1"})
    assert lookup._target_role_arn() == "arn:aws-us-gov:iam::%s:role/%s" % (TARGET_ACCOUNT, ROLE)
    lookup.set_options(direct={"account": TARGET_ACCOUNT, "role_name": ROLE, "region": "us-gov-west-1", "partition": "aws"})
    assert lookup._target_role_arn() == "arn:aws:iam::%s:role/%s" % (TARGET_ACCOUNT, ROLE)


# ---- missing / denied ----------------------------------------------------------


def test_missing_errors_by_default(lookup):
    with pytest.raises(AnsibleLookupError, match="/nope not found"):
        lookup.run(["/nope"], {}, region=REGION)


@pytest.mark.parametrize("action", ["skip", "warn"])
def test_missing_skip_and_warn(lookup, action):
    boto3.client("ssm", region_name=REGION).put_parameter(Name="/a", Value="1", Type="String")
    with patch.object(lookup._display, "warning") as warning:
        assert lookup.run(["/a", "/nope"], {}, region=REGION, on_missing=action) == ["1", None]
    assert warning.called == (action == "warn")


@pytest.mark.parametrize("action, expect_error", [("error", True), ("skip", False), ("warn", False)])
def test_denied(lookup, action, expect_error):
    err = plugin.botocore.exceptions.ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "denied"}}, "GetParameter"
    )
    fake_ssm = MagicMock()
    fake_ssm.get_parameter.side_effect = err
    with patch.object(plugin.LookupModule, "_make_client", return_value=fake_ssm):
        if expect_error:
            with pytest.raises(AnsibleLookupError, match="Access denied"):
                lookup.run(["/p"], {}, region=REGION, on_denied=action)
        else:
            assert lookup.run(["/p"], {}, region=REGION, on_denied=action) == [None]


# ---- bypath --------------------------------------------------------------------


@pytest.fixture
def path_params():
    ssm = _target_ssm()
    ssm.put_parameter(Name="/app/prod/db/host", Value="db.internal", Type="String")
    ssm.put_parameter(Name="/app/prod/db/pass", Value="pw", Type="SecureString")
    ssm.put_parameter(Name="/app/prod/region", Value="us-east-1", Type="String")
    return dict(region=REGION, account=TARGET_ACCOUNT, role_name=ROLE, bypath=True)


def test_bypath_non_recursive(lookup, path_params):
    assert lookup.run(["/app/prod"], {}, **path_params) == [{"/app/prod/region": "us-east-1"}]


def test_bypath_recursive(lookup, path_params):
    (result,) = lookup.run(["/app/prod"], {}, recursive=True, **path_params)
    assert result == {
        "/app/prod/db/host": "db.internal",
        "/app/prod/db/pass": "pw",
        "/app/prod/region": "us-east-1",
    }


def test_bypath_shortnames(lookup, path_params):
    (result,) = lookup.run(["/app/prod"], {}, recursive=True, shortnames=True, **path_params)
    assert result == {"host": "db.internal", "pass": "pw", "region": "us-east-1"}


def test_bypath_droppath(lookup, path_params):
    (result,) = lookup.run(["/app/prod/"], {}, recursive=True, droppath=True, **path_params)
    assert result == {"db/host": "db.internal", "db/pass": "pw", "region": "us-east-1"}


# ---- validation ----------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"account": TARGET_ACCOUNT}, "must be given together"),
        ({"role_name": ROLE}, "must be given together"),
        ({"account": "1234", "role_name": ROLE}, "12 digit"),
        ({"role_arn": "arn:aws:iam::%s:role/x" % TARGET_ACCOUNT, "account": TARGET_ACCOUNT, "role_name": ROLE}, "cannot be combined"),
        ({"role_arn": "not-an-arn"}, "does not look like"),
        ({"profile": "x", "access_key": "a", "secret_key": "b"}, "cannot be combined"),
        ({"access_key": "a"}, "must be given together"),
        ({"duration_seconds": 60, "role_arn": "arn:aws:iam::%s:role/x" % TARGET_ACCOUNT}, "between 900 and 43200"),
    ],
)
def test_invalid_options(lookup, kwargs, message):
    with pytest.raises(AnsibleLookupError, match=message):
        lookup.run(["/p"], {}, region=REGION, **kwargs)


def test_missing_region(lookup):
    with pytest.raises(AnsibleLookupError, match="No AWS region"):
        lookup.run(["/p"], {})


def test_unknown_profile(lookup):
    with pytest.raises(AnsibleLookupError, match="profile not found"):
        lookup.run(["/p"], {}, region=REGION, profile="does-not-exist")
