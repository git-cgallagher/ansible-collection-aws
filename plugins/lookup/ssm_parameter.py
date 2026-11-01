# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Chris Gallagher
# MIT License (see LICENSE or https://opensource.org/licenses/MIT)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
name: ssm_parameter
author:
  - Chris Gallagher (@git-cgallagher)
short_description: Get values from AWS SSM Parameter Store, optionally through an assumed IAM role
version_added: 0.1.0
description:
  - Look up one or more parameters from AWS Systems Manager Parameter Store.
  - Can assume an IAM role in another account before the lookup, by giving O(account) and O(role_name)
    (or a full O(role_arn)). This is the main difference from the P(amazon.aws.ssm_parameter#lookup) lookup.
  - Assumed role credentials are cached for the life of the Ansible process and reused until shortly before
    they expire, so looping over many parameters or hosts makes one C(sts:AssumeRole) call per role.
  - The base credentials used to call C(sts:AssumeRole) come from O(profile), O(access_key)/O(secret_key),
    or the standard boto3 credential chain (environment, shared config, instance profile, and so on).
  - All options can be given as keyword arguments to the lookup.
options:
  _terms:
    description:
      - Parameter names to look up.
      - With O(bypath=true), parameter paths to look up instead.
    type: list
    elements: str
    required: true
  account:
    description:
      - AWS account ID (12 digits) that holds the role to assume.
      - Used with O(role_name) to build the role ARN.
      - Mutually exclusive with O(role_arn).
    type: str
    aliases: [account_id]
  role_name:
    description:
      - Name of the IAM role to assume in O(account). May include a path, for example C(service-role/ParamReader).
      - Requires O(account).
      - Mutually exclusive with O(role_arn).
    type: str
  role_arn:
    description:
      - Full ARN of the IAM role to assume. Use this instead of O(account) and O(role_name) when convenient.
    type: str
  role_session_name:
    description:
      - Session name used for C(sts:AssumeRole). Shows up in CloudTrail.
    type: str
    default: ansible-ssm-lookup
  external_id:
    description:
      - External ID to pass to C(sts:AssumeRole), if the role's trust policy requires one.
    type: str
  duration_seconds:
    description:
      - Lifetime of the assumed role session, in seconds.
    type: int
    default: 3600
  partition:
    description:
      - AWS partition used when building the role ARN from O(account) and O(role_name).
      - When not set, it is worked out from O(region) (C(aws-cn) for C(cn-*), C(aws-us-gov) for C(us-gov-*), otherwise C(aws)).
    type: str
    choices: [aws, aws-cn, aws-us-gov, aws-iso, aws-iso-b]
  region:
    description:
      - AWS region to query, and the region used for the STS call.
    type: str
    aliases: [aws_region]
    env:
      - name: AWS_REGION
      - name: AWS_DEFAULT_REGION
  profile:
    description:
      - Named profile from the AWS shared config to use as the base credentials.
      - Mutually exclusive with O(access_key), O(secret_key) and O(session_token).
    type: str
    aliases: [aws_profile]
    env:
      - name: AWS_PROFILE
  access_key:
    description:
      - AWS access key ID to use as the base credentials.
    type: str
    aliases: [aws_access_key_id, aws_access_key]
  secret_key:
    description:
      - AWS secret access key to use as the base credentials.
    type: str
    aliases: [aws_secret_access_key, aws_secret_key]
  session_token:
    description:
      - AWS session token to use with O(access_key) and O(secret_key).
    type: str
    aliases: [aws_session_token]
  endpoint_url:
    description:
      - Custom endpoint for the SSM service, for example a VPC endpoint.
    type: str
  sts_endpoint_url:
    description:
      - Custom endpoint for the STS service, for example a VPC endpoint or regional endpoint.
    type: str
  decrypt:
    description:
      - Decrypt C(SecureString) parameters.
    type: bool
    default: true
  bypath:
    description:
      - Treat each term as a path and return every parameter under it as a dictionary of name to value.
    type: bool
    default: false
  recursive:
    description:
      - With O(bypath=true), also return parameters in nested paths.
    type: bool
    default: false
  shortnames:
    description:
      - With O(bypath=true), use only the last path segment of each parameter name as its key.
    type: bool
    default: false
  droppath:
    description:
      - With O(bypath=true), remove the looked-up path from the start of each key.
      - Ignored when O(shortnames=true).
    type: bool
    default: false
  on_missing:
    description:
      - What to do when a parameter does not exist.
      - V(error) fails the lookup, V(skip) returns C(None) for it, V(warn) returns C(None) and prints a warning.
      - Not used with O(bypath=true).
    type: str
    choices: [error, skip, warn]
    default: error
  on_denied:
    description:
      - What to do when access to a parameter is denied.
      - V(error) fails the lookup, V(skip) returns C(None) for it, V(warn) returns C(None) and prints a warning.
    type: str
    choices: [error, skip, warn]
    default: error
notes:
  - Requires C(boto3) and C(botocore) on the controller.
  - The base credentials need C(sts:AssumeRole) on the target role, and the target role needs C(ssm:GetParameter)
    (or C(ssm:GetParametersByPath) for O(bypath=true)) plus C(kms:Decrypt) on the key used by any C(SecureString).
  - Lookups run on the controller, not on the managed hosts.
"""

EXAMPLES = r"""
- name: Read a parameter from the current credentials' account
  ansible.builtin.debug:
    msg: "{{ lookup('git_cgallagher.aws.ssm_parameter', '/app/db/host', region='us-east-1') }}"

- name: Read a SecureString from another account by assuming a role
  ansible.builtin.debug:
    msg: >-
      {{ lookup('git_cgallagher.aws.ssm_parameter', '/app/db/password',
                account='123456789012', role_name='ParamReader', region='us-west-2') }}

- name: Same, with a full role ARN and an external ID
  ansible.builtin.debug:
    msg: >-
      {{ lookup('git_cgallagher.aws.ssm_parameter', '/app/db/password',
                role_arn='arn:aws:iam::123456789012:role/ParamReader',
                external_id='s3cr3t-ext-id', region='us-west-2') }}

- name: Several parameters at once (returns a list)
  ansible.builtin.set_fact:
    db_settings: >-
      {{ query('git_cgallagher.aws.ssm_parameter', '/app/db/host', '/app/db/port',
               account=target_account, role_name='ParamReader', region=aws_region) }}

- name: Everything under a path, keyed by short name
  ansible.builtin.set_fact:
    app_config: >-
      {{ lookup('git_cgallagher.aws.ssm_parameter', '/app/prod/', bypath=true, recursive=true,
                shortnames=true, account='123456789012', role_name='ParamReader',
                region='eu-west-1') }}

- name: Optional parameter that may not exist yet
  ansible.builtin.debug:
    msg: >-
      {{ lookup('git_cgallagher.aws.ssm_parameter', '/app/feature_flag', on_missing='skip',
                account='123456789012', role_name='ParamReader', region='us-east-1')
         | default('off', true) }}

- name: Per-host account and region from inventory
  ansible.builtin.debug:
    msg: >-
      {{ lookup('git_cgallagher.aws.ssm_parameter', '/platform/' ~ inventory_hostname ~ '/token',
                account=aws_account_id, role_name='AnsibleParamReader', region=aws_region) }}
"""

RETURN = r"""
_raw:
  description:
    - One value per term.
    - Without O(bypath), the parameter's value as a string, or C(None) for a skipped missing or denied parameter.
      C(StringList) values are returned as the raw comma-separated string; use the C(split) filter to get a list.
    - With O(bypath=true), a dictionary of parameter name to value.
  type: list
  elements: raw
"""

import re
import threading
from datetime import datetime, timedelta, timezone

try:
    import boto3
    import boto3.session
    import botocore.exceptions

    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False

from ansible.errors import AnsibleLookupError
from ansible.module_utils.common.text.converters import to_native
from ansible.plugins.lookup import LookupBase
from ansible.utils.display import Display

display = Display()

_ACCOUNT_RE = re.compile(r"^\d{12}$")
_ROLE_ARN_RE = re.compile(r"^arn:aws[a-z-]*:iam::\d{12}:role/.+$")

# Refresh assumed credentials this long before they actually expire.
_EXPIRY_MARGIN = timedelta(minutes=5)

# Process-wide cache of assumed role credentials, so loops and many hosts reuse one STS session.
_CRED_CACHE = {}
_CRED_LOCK = threading.Lock()

_DENIED_CODES = frozenset(
    (
        "AccessDenied",
        "AccessDeniedException",
        "UnauthorizedOperation",
        "UnrecognizedClientException",
    )
)


def _partition_for_region(region):
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


def _error_code(exc):
    return exc.response.get("Error", {}).get("Code", "")


class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        if not HAS_BOTO3:
            raise AnsibleLookupError("The git_cgallagher.aws.ssm_parameter lookup requires the boto3 and botocore Python libraries.")

        self.set_options(var_options=variables, direct=kwargs)
        self._validate_options()

        session = self._get_session()
        client = self._make_client(session, "ssm", self.get_option("endpoint_url"))

        if self.get_option("bypath"):
            return [self._get_by_path(client, term) for term in terms]
        return [self._get_one(client, term) for term in terms]

    # ---- options -----------------------------------------------------------

    def _validate_options(self):
        account = self.get_option("account")
        role_name = self.get_option("role_name")
        role_arn = self.get_option("role_arn")

        if role_arn and (account or role_name):
            raise AnsibleLookupError("'role_arn' cannot be combined with 'account' or 'role_name'.")
        if bool(account) != bool(role_name):
            raise AnsibleLookupError("'account' and 'role_name' must be given together.")
        if account and not _ACCOUNT_RE.match(str(account)):
            raise AnsibleLookupError("'account' must be a 12 digit AWS account ID, got %r." % account)
        if role_arn and not _ROLE_ARN_RE.match(role_arn):
            raise AnsibleLookupError("'role_arn' does not look like an IAM role ARN: %r." % role_arn)

        if self.get_option("profile") and (self.get_option("access_key") or self.get_option("secret_key") or self.get_option("session_token")):
            raise AnsibleLookupError("'profile' cannot be combined with 'access_key', 'secret_key' or 'session_token'.")
        if bool(self.get_option("access_key")) != bool(self.get_option("secret_key")):
            raise AnsibleLookupError("'access_key' and 'secret_key' must be given together.")

        duration = self.get_option("duration_seconds")
        if duration is not None and not 900 <= duration <= 43200:
            raise AnsibleLookupError("'duration_seconds' must be between 900 and 43200.")

    def _target_role_arn(self):
        role_arn = self.get_option("role_arn")
        if role_arn:
            return role_arn
        account = self.get_option("account")
        if not account:
            return None
        role_name = self.get_option("role_name").strip("/")
        partition = self.get_option("partition") or _partition_for_region(self.get_option("region"))
        return "arn:%s:iam::%s:role/%s" % (partition, account, role_name)

    # ---- sessions and credentials ------------------------------------------

    def _base_session(self):
        kwargs = {}
        if self.get_option("profile"):
            kwargs["profile_name"] = self.get_option("profile")
        if self.get_option("access_key"):
            kwargs["aws_access_key_id"] = self.get_option("access_key")
            kwargs["aws_secret_access_key"] = self.get_option("secret_key")
            if self.get_option("session_token"):
                kwargs["aws_session_token"] = self.get_option("session_token")
        if self.get_option("region"):
            kwargs["region_name"] = self.get_option("region")
        try:
            return boto3.session.Session(**kwargs)
        except botocore.exceptions.ProfileNotFound as e:
            raise AnsibleLookupError("AWS profile not found: %s" % to_native(e))

    def _get_session(self):
        base = self._base_session()
        role_arn = self._target_role_arn()
        if not role_arn:
            return base

        creds = self._assumed_credentials(base, role_arn)
        return boto3.session.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
            region_name=self.get_option("region") or base.region_name,
        )

    def _cache_key(self, base, role_arn):
        base_creds = base.get_credentials()
        base_id = base_creds.access_key if base_creds else None
        return (
            base_id,
            role_arn,
            self.get_option("role_session_name"),
            self.get_option("external_id"),
            self.get_option("duration_seconds"),
        )

    def _assumed_credentials(self, base, role_arn):
        key = self._cache_key(base, role_arn)
        now = datetime.now(timezone.utc)

        with _CRED_LOCK:
            cached = _CRED_CACHE.get(key)
            if cached and cached["Expiration"] - _EXPIRY_MARGIN > now:
                return cached

            sts = self._make_client(base, "sts", self.get_option("sts_endpoint_url"))
            params = {
                "RoleArn": role_arn,
                "RoleSessionName": self.get_option("role_session_name"),
                "DurationSeconds": self.get_option("duration_seconds"),
            }
            if self.get_option("external_id"):
                params["ExternalId"] = self.get_option("external_id")

            display.vvv("git_cgallagher.aws.ssm_parameter: assuming role %s" % role_arn)
            try:
                creds = sts.assume_role(**params)["Credentials"]
            except botocore.exceptions.ClientError as e:
                raise AnsibleLookupError("Failed to assume role %s: %s" % (role_arn, to_native(e)))
            except botocore.exceptions.BotoCoreError as e:
                raise AnsibleLookupError("Failed to assume role %s: %s" % (role_arn, to_native(e)))

            expiration = creds["Expiration"]
            if expiration.tzinfo is None:
                expiration = expiration.replace(tzinfo=timezone.utc)
            creds["Expiration"] = expiration

            _CRED_CACHE[key] = creds
            return creds

    def _make_client(self, session, service, endpoint_url):
        region = self.get_option("region") or session.region_name
        if not region:
            raise AnsibleLookupError("No AWS region set. Pass 'region' to the lookup or set AWS_REGION.")
        kwargs = {"region_name": region}
        if endpoint_url:
            kwargs["endpoint_url"] = endpoint_url
        try:
            return session.client(service, **kwargs)
        except botocore.exceptions.BotoCoreError as e:
            raise AnsibleLookupError("Failed to create %s client: %s" % (service, to_native(e)))

    # ---- lookups -----------------------------------------------------------

    def _handle(self, setting, message):
        action = self.get_option(setting)
        if action == "error":
            raise AnsibleLookupError(message)
        if action == "warn":
            self._display.warning(message)
        return None

    def _get_one(self, client, name):
        try:
            response = client.get_parameter(Name=name, WithDecryption=self.get_option("decrypt"))
        except botocore.exceptions.ClientError as e:
            code = _error_code(e)
            if code == "ParameterNotFound":
                return self._handle("on_missing", "Parameter %s not found." % name)
            if code in _DENIED_CODES:
                return self._handle("on_denied", "Access denied to parameter %s: %s" % (name, to_native(e)))
            raise AnsibleLookupError("Failed to get parameter %s: %s" % (name, to_native(e)))
        except botocore.exceptions.BotoCoreError as e:
            raise AnsibleLookupError("Failed to get parameter %s: %s" % (name, to_native(e)))
        return response["Parameter"]["Value"]

    def _get_by_path(self, client, path):
        result = {}
        try:
            paginator = client.get_paginator("get_parameters_by_path")
            pages = paginator.paginate(
                Path=path,
                Recursive=self.get_option("recursive"),
                WithDecryption=self.get_option("decrypt"),
            )
            for page in pages:
                for param in page.get("Parameters", []):
                    result[self._key_for(path, param["Name"])] = param["Value"]
        except botocore.exceptions.ClientError as e:
            if _error_code(e) in _DENIED_CODES:
                return self._handle("on_denied", "Access denied to path %s: %s" % (path, to_native(e)))
            raise AnsibleLookupError("Failed to get parameters under %s: %s" % (path, to_native(e)))
        except botocore.exceptions.BotoCoreError as e:
            raise AnsibleLookupError("Failed to get parameters under %s: %s" % (path, to_native(e)))
        return result

    def _key_for(self, path, name):
        if self.get_option("shortnames"):
            return name.rsplit("/", 1)[-1]
        if self.get_option("droppath"):
            prefix = path if path.endswith("/") else path + "/"
            if name.startswith(prefix):
                return name[len(prefix):]
        return name
