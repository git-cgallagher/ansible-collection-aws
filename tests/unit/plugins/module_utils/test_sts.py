# -*- coding: utf-8 -*-
# MIT License (see LICENSE or https://opensource.org/licenses/MIT)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

from datetime import datetime, timedelta, timezone

import pytest

boto3 = pytest.importorskip("boto3")
moto = pytest.importorskip("moto")

from ansible_collections.git_cgallagher.aws.plugins.module_utils import sts

REGION = "us-east-1"
HUB = "arn:aws:iam::111111111111:role/Hub"
SPOKE = "arn:aws:iam::222222222222:role/Spoke"


@pytest.fixture(autouse=True)
def aws_env(monkeypatch):
    for var in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_REGION", "AWS_DEFAULT_REGION"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    with moto.mock_aws():
        yield


def _account(session):
    return session.client("sts", region_name=REGION).get_caller_identity()["Account"]


def _opts(**kwargs):
    opts = dict((name, None) for name in sts.ROLE_OPTIONS)
    opts.update(region=REGION, role_session_name="test", duration_seconds=3600)
    opts.update(kwargs)
    return opts


def test_no_role_returns_base_session():
    session = sts.chained_session(_opts())
    assert _account(session) == "123456789012"


def test_role_chain_order():
    assert sts.role_chain(_opts()) == []
    assert sts.role_chain(_opts(role_arn=SPOKE)) == [SPOKE]
    assert sts.role_chain(_opts(via_role_arns=[HUB], account="222222222222", role_name="/Spoke/")) == [HUB, SPOKE]


def test_chained_session_ends_in_target_account():
    session = sts.chained_session(_opts(via_role_arns=[HUB], role_arn=SPOKE))
    assert _account(session) == "222222222222"


def test_cache_is_per_hop():
    cache = {}
    sts.chained_session(_opts(via_role_arns=[HUB], role_arn=SPOKE), cache=cache)
    assert sorted(key[1] for key in cache) == [HUB, SPOKE]
    hub_key = [key for key in cache if key[1] == HUB][0]
    hub_creds = cache[hub_key]

    # A second spoke behind the same hub reuses the hub entry.
    other = "arn:aws:iam::333333333333:role/Other"
    sts.chained_session(_opts(via_role_arns=[HUB], role_arn=other), cache=cache)
    assert cache[hub_key] is hub_creds
    assert len(cache) == 3


def test_expired_cache_entry_is_refreshed():
    cache = {}
    sts.chained_session(_opts(role_arn=SPOKE), cache=cache)
    (key,) = list(cache)
    cache[key]["Expiration"] = datetime.now(timezone.utc) + timedelta(minutes=1)
    sts.chained_session(_opts(role_arn=SPOKE), cache=cache)
    assert cache[key]["Expiration"] > datetime.now(timezone.utc) + timedelta(minutes=10)


@pytest.mark.parametrize(
    "region, expected",
    [
        ("us-east-1", "aws"),
        ("cn-north-1", "aws-cn"),
        ("us-gov-west-1", "aws-us-gov"),
        ("us-iso-east-1", "aws-iso"),
        ("us-isob-east-1", "aws-iso-b"),
        (None, "aws"),
    ],
)
def test_partition_for_region(region, expected):
    assert sts.partition_for_region(region) == expected


def test_validate_chained_duration():
    sts.validate_role_options(_opts(via_role_arns=[HUB], role_arn=SPOKE, duration_seconds=3600))
    with pytest.raises(sts.StsError, match="cannot exceed 3600"):
        sts.validate_role_options(_opts(via_role_arns=[HUB], role_arn=SPOKE, duration_seconds=3601))
    sts.validate_role_options(_opts(role_arn=SPOKE, duration_seconds=7200))


def test_role_argument_spec_matches_role_options():
    assert tuple(sts.role_argument_spec("x")) == sts.ROLE_OPTIONS
