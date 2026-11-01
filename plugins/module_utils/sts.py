# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Chris Gallagher
# MIT License (see LICENSE or https://opensource.org/licenses/MIT)

"""Shared boto3 session and sts:AssumeRole helpers for the collection's plugins.

Used by the ssm_parameter lookup (controller side) and the ssm_parameter module
(target side), so it stays plain Python 3 with no Ansible imports beyond the
module_utils tree.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import re
from datetime import datetime, timedelta, timezone

try:
    import boto3
    import boto3.session
    import botocore.exceptions

    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False

ACCOUNT_RE = re.compile(r"^\d{12}$")
ROLE_ARN_RE = re.compile(r"^arn:aws[a-z-]*:iam::\d{12}:role/.+$")

# AWS caps a session obtained with role-chained credentials at one hour.
CHAINED_MAX_DURATION = 3600

# Refresh cached credentials this long before they actually expire.
EXPIRY_MARGIN = timedelta(minutes=5)


class StsError(Exception):
    """Raised for option problems and STS failures; callers turn it into their own error type."""


def partition_for_region(region):
    if not region:
        return "aws"
    if region.startswith("cn-"):
        return "aws-cn"
    if region.startswith("us-gov-"):
        return "aws-us-gov"
    if region.startswith("us-isob-"):
        return "aws-iso-b"
    if region.startswith("us-iso-"):
        return "aws-iso"
    return "aws"


def error_code(exc):
    return exc.response.get("Error", {}).get("Code", "")


def validate_role_options(opts):
    """Check the role and credential options shared by the plugins. opts is a dict of option name to value."""
    account = opts.get("account")
    role_name = opts.get("role_name")
    role_arn = opts.get("role_arn")
    via = opts.get("via_role_arns") or []

    if role_arn and (account or role_name):
        raise StsError("'role_arn' cannot be combined with 'account' or 'role_name'.")
    if bool(account) != bool(role_name):
        raise StsError("'account' and 'role_name' must be given together.")
    if account and not ACCOUNT_RE.match(str(account)):
        raise StsError("'account' must be a 12 digit AWS account ID, got %r." % account)
    if role_arn and not ROLE_ARN_RE.match(role_arn):
        raise StsError("'role_arn' does not look like an IAM role ARN: %r." % role_arn)
    for arn in via:
        if not ROLE_ARN_RE.match(arn):
            raise StsError("'via_role_arns' entry does not look like an IAM role ARN: %r." % arn)
    if via and not (role_arn or account):
        raise StsError("'via_role_arns' needs a target role: give 'role_arn', or 'account' and 'role_name'.")

    if opts.get("profile") and (opts.get("access_key") or opts.get("secret_key") or opts.get("session_token")):
        raise StsError("'profile' cannot be combined with 'access_key', 'secret_key' or 'session_token'.")
    if bool(opts.get("access_key")) != bool(opts.get("secret_key")):
        raise StsError("'access_key' and 'secret_key' must be given together.")

    duration = opts.get("duration_seconds")
    if duration is not None and not 900 <= duration <= 43200:
        raise StsError("'duration_seconds' must be between 900 and 43200.")
    if via and duration is not None and duration > CHAINED_MAX_DURATION:
        raise StsError("'duration_seconds' cannot exceed %d when 'via_role_arns' is set: AWS limits role-chained sessions to one hour." % CHAINED_MAX_DURATION)


def target_role_arn(opts):
    """The role to end up in, or None when the base credentials are used directly."""
    if opts.get("role_arn"):
        return opts["role_arn"]
    account = opts.get("account")
    if not account:
        return None
    role_name = opts["role_name"].strip("/")
    partition = opts.get("partition") or partition_for_region(opts.get("region"))
    return "arn:%s:iam::%s:role/%s" % (partition, account, role_name)


def base_session(opts):
    """boto3 session from profile, explicit keys, or the default credential chain."""
    kwargs = {}
    if opts.get("profile"):
        kwargs["profile_name"] = opts["profile"]
    if opts.get("access_key"):
        kwargs["aws_access_key_id"] = opts["access_key"]
        kwargs["aws_secret_access_key"] = opts["secret_key"]
        if opts.get("session_token"):
            kwargs["aws_session_token"] = opts["session_token"]
    if opts.get("region"):
        kwargs["region_name"] = opts["region"]
    try:
        return boto3.session.Session(**kwargs)
    except botocore.exceptions.ProfileNotFound as e:
        raise StsError("AWS profile not found: %s" % e)


def session_from_credentials(creds, region):
    return boto3.session.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
        region_name=region,
    )


def make_client(session, service, region, endpoint_url=None):
    region = region or session.region_name
    if not region:
        raise StsError("No AWS region set. Pass 'region' or set AWS_REGION.")
    kwargs = {"region_name": region}
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    try:
        return session.client(service, **kwargs)
    except botocore.exceptions.BotoCoreError as e:
        raise StsError("Failed to create %s client: %s" % (service, e))


def assume_role(session, role_arn, session_name, duration, external_id=None, region=None, sts_endpoint_url=None):
    """One sts:AssumeRole call. Returns the Credentials dict with a timezone-aware Expiration."""
    sts = make_client(session, "sts", region, sts_endpoint_url)
    params = {"RoleArn": role_arn, "RoleSessionName": session_name, "DurationSeconds": duration}
    if external_id:
        params["ExternalId"] = external_id
    try:
        creds = sts.assume_role(**params)["Credentials"]
    except (botocore.exceptions.ClientError, botocore.exceptions.BotoCoreError) as e:
        raise StsError("Failed to assume role %s: %s" % (role_arn, e))
    expiration = creds["Expiration"]
    if expiration.tzinfo is None:
        expiration = expiration.replace(tzinfo=timezone.utc)
    creds["Expiration"] = expiration
    return creds


def role_chain(opts):
    """The roles to assume in order: every via_role_arns entry, then the target. Empty when no role is involved."""
    target = target_role_arn(opts)
    if not target:
        return []
    return list(opts.get("via_role_arns") or []) + [target]


def chained_session(opts, cache=None, lock=None, on_assume=None):
    """Session for the target role, assuming every hop in role_chain(opts) from the base session.

    cache: optional dict of hop key -> Credentials, shared across calls so repeated lookups reuse
    sessions until shortly before they expire. Each hop is cached on its own, so one hub session
    serves many spokes. lock: optional threading.Lock guarding the cache. on_assume: optional
    callable(role_arn) called right before each real STS call (for verbose logging).
    """
    base = base_session(opts)
    chain = role_chain(opts)
    if not chain:
        return base

    region = opts.get("region")
    session = base
    last = len(chain) - 1
    for index, role_arn in enumerate(chain):
        final = index == last
        duration = opts.get("duration_seconds") if final else CHAINED_MAX_DURATION
        if final and len(chain) > 1:
            duration = min(duration, CHAINED_MAX_DURATION)
        external_id = opts.get("external_id") if final else None
        session_name = opts.get("role_session_name")

        creds = None
        key = None
        if cache is not None:
            base_creds = session.get_credentials()
            key = (base_creds.access_key if base_creds else None, role_arn, session_name, external_id, duration)
            creds = _cached(cache, lock, key)
        if creds is None:
            if on_assume:
                on_assume(role_arn)
            creds = assume_role(session, role_arn, session_name, duration, external_id, region, opts.get("sts_endpoint_url"))
            if cache is not None:
                _store(cache, lock, key, creds)
        session = session_from_credentials(creds, region or base.region_name)
    return session


def _cached(cache, lock, key):
    now = datetime.now(timezone.utc)
    if lock:
        lock.acquire()
    try:
        creds = cache.get(key)
        if creds and creds["Expiration"] - EXPIRY_MARGIN > now:
            return creds
        return None
    finally:
        if lock:
            lock.release()


def _store(cache, lock, key, creds):
    if lock:
        lock.acquire()
    try:
        cache[key] = creds
    finally:
        if lock:
            lock.release()


# Option names shared by every plugin that assumes a role; mirrored by the aws_role doc fragment.
ROLE_OPTIONS = (
    "account",
    "role_name",
    "role_arn",
    "via_role_arns",
    "role_session_name",
    "external_id",
    "duration_seconds",
    "partition",
    "region",
    "profile",
    "access_key",
    "secret_key",
    "session_token",
    "endpoint_url",
    "sts_endpoint_url",
)


def role_argument_spec(session_name_default):
    """AnsibleModule argument_spec entries matching the aws_role doc fragment."""
    return dict(
        account=dict(type="str", aliases=["account_id"]),
        role_name=dict(type="str"),
        role_arn=dict(type="str"),
        via_role_arns=dict(type="list", elements="str"),
        role_session_name=dict(type="str", default=session_name_default),
        external_id=dict(type="str"),
        duration_seconds=dict(type="int", default=3600),
        partition=dict(type="str", choices=["aws", "aws-cn", "aws-us-gov", "aws-iso", "aws-iso-b"]),
        region=dict(type="str", aliases=["aws_region"]),
        profile=dict(type="str", aliases=["aws_profile"]),
        access_key=dict(type="str", aliases=["aws_access_key_id", "aws_access_key"], no_log=False),
        secret_key=dict(type="str", aliases=["aws_secret_access_key", "aws_secret_key"], no_log=True),
        session_token=dict(type="str", aliases=["aws_session_token"], no_log=True),
        endpoint_url=dict(type="str"),
        sts_endpoint_url=dict(type="str"),
    )
