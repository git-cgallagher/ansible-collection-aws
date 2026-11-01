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
  - Can chain through intermediate roles first with O(via_role_arns), for controllers that reach the target
    account through a hub role.
  - Assumed role credentials are cached per hop for the life of the Ansible process and reused until shortly
    before they expire, so looping over many parameters or hosts makes one C(sts:AssumeRole) call per role,
    and one hub session serves every spoke behind it.
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
  role_session_name:
    default: ansible-ssm-lookup
  region:
    env:
      - name: AWS_REGION
      - name: AWS_DEFAULT_REGION
  profile:
    env:
      - name: AWS_PROFILE
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
extends_documentation_fragment:
  - git_cgallagher.aws.aws_role
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

- name: Through a hub role the controller can assume, then the spoke account's role
  ansible.builtin.debug:
    msg: >-
      {{ lookup('git_cgallagher.aws.ssm_parameter', '/app/db/password',
                via_role_arns=['arn:aws:iam::999999999999:role/Hub'],
                account='123456789012', role_name='ParamReader', region='us-west-2') }}

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

import threading

try:
    import botocore.exceptions  # noqa: F401  (re-exported for callers and tests)
except ImportError:
    pass

from ansible.errors import AnsibleLookupError
from ansible.module_utils.common.text.converters import to_native
from ansible.plugins.lookup import LookupBase
from ansible.utils.display import Display

from ansible_collections.git_cgallagher.aws.plugins.module_utils import sts

display = Display()

# Process-wide cache of assumed role credentials (one entry per hop), so loops and many hosts reuse one STS session.
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

_partition_for_region = sts.partition_for_region
_error_code = sts.error_code


class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        if not sts.HAS_BOTO3:
            raise AnsibleLookupError("The git_cgallagher.aws.ssm_parameter lookup requires the boto3 and botocore Python libraries.")

        self.set_options(var_options=variables, direct=kwargs)
        self._validate_options()

        session = self._get_session()
        client = self._make_client(session, "ssm", self.get_option("endpoint_url"))

        if self.get_option("bypath"):
            return [self._get_by_path(client, term) for term in terms]
        return [self._get_one(client, term) for term in terms]

    # ---- options -----------------------------------------------------------

    def _role_options(self):
        return dict((name, self.get_option(name)) for name in sts.ROLE_OPTIONS)

    def _validate_options(self):
        try:
            sts.validate_role_options(self._role_options())
        except sts.StsError as e:
            raise AnsibleLookupError(to_native(e))

    def _target_role_arn(self):
        return sts.target_role_arn(self._role_options())

    # ---- sessions and credentials ------------------------------------------

    def _get_session(self):
        try:
            return sts.chained_session(
                self._role_options(),
                cache=_CRED_CACHE,
                lock=_CRED_LOCK,
                on_assume=lambda arn: display.vvv("git_cgallagher.aws.ssm_parameter: assuming role %s" % arn),
            )
        except sts.StsError as e:
            raise AnsibleLookupError(to_native(e))

    def _make_client(self, session, service, endpoint_url):
        try:
            return sts.make_client(session, service, self.get_option("region"), endpoint_url)
        except sts.StsError as e:
            raise AnsibleLookupError(to_native(e))

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
