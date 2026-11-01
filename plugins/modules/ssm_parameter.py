#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Chris Gallagher
# MIT License (see LICENSE or https://opensource.org/licenses/MIT)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
module: ssm_parameter
short_description: Create, update or delete AWS SSM Parameter Store parameters, optionally through an assumed IAM role
version_added: 0.2.0
description:
  - Manage a parameter in AWS Systems Manager Parameter Store.
  - Can assume an IAM role in another account first, by giving O(account) and O(role_name) (or a full O(role_arn)),
    and can chain through intermediate roles with O(via_role_arns). This is the difference from the
    M(amazon.aws.ssm_parameter) module, which only uses the credentials it is given.
  - Runs wherever the task runs, so delegate it to C(localhost) (or run the play on localhost) unless the managed
    host has boto3 and AWS credentials of its own.
author:
  - Chris Gallagher (@git-cgallagher)
options:
  name:
    description:
      - Name of the parameter, for example C(/app/prod/db/password).
    type: str
    required: true
  value:
    description:
      - Value of the parameter.
      - Required with O(state=present).
    type: str
  string_type:
    description:
      - Type of the parameter.
    type: str
    choices: [String, StringList, SecureString]
    default: String
  description:
    description:
      - Description of the parameter.
      - When not set, an existing parameter keeps its description.
    type: str
  key_id:
    description:
      - KMS key ID or alias used to encrypt a C(SecureString) parameter. AWS uses C(alias/aws/ssm) when not set.
    type: str
  tier:
    description:
      - Parameter tier. AWS uses C(Standard) when not set.
    type: str
    choices: [Standard, Advanced, Intelligent-Tiering]
  overwrite_value:
    description:
      - What to do when the parameter already exists.
      - V(never) leaves it alone, V(changed) updates it only when the value, type, description, tier or key differ,
        V(always) writes a new version every time.
    type: str
    choices: [never, changed, always]
    default: changed
  state:
    description:
      - Whether the parameter should exist.
    type: str
    choices: [present, absent]
    default: present
  role_session_name:
    default: ansible-ssm-parameter
extends_documentation_fragment:
  - git_cgallagher.aws.aws_role
attributes:
  check_mode:
    description: Can run in check mode and return changed status prediction without modifying the parameter.
    support: full
  diff_mode:
    description: Does not return a diff; parameter values are never shown.
    support: none
notes:
  - Requires C(boto3) and C(botocore) where the module runs.
  - The base credentials need C(sts:AssumeRole) on the first role in the chain, and the target role needs
    C(ssm:GetParameter), C(ssm:DescribeParameters) and C(ssm:PutParameter) (plus C(ssm:DeleteParameter) for
    O(state=absent)) and C(kms:Encrypt)/C(kms:Decrypt) on the key used by any C(SecureString).
  - The parameter's value is never returned; read it back with the P(git_cgallagher.aws.ssm_parameter#lookup) lookup.
"""

EXAMPLES = r"""
- name: Write a SecureString into another account by assuming a role there
  git_cgallagher.aws.ssm_parameter:
    name: /app/prod/db/password
    value: "{{ db_password }}"
    string_type: SecureString
    account: '123456789012'
    role_name: ParamWriter
    region: us-west-2
  delegate_to: localhost
  no_log: true

- name: Same, through a hub role the controller can assume
  git_cgallagher.aws.ssm_parameter:
    name: /app/prod/db/password
    value: "{{ db_password }}"
    string_type: SecureString
    via_role_arns:
      - arn:aws:iam::999999999999:role/Hub
    account: '123456789012'
    role_name: ParamWriter
    region: us-west-2
  delegate_to: localhost
  no_log: true

- name: Create a parameter once and never touch it again
  git_cgallagher.aws.ssm_parameter:
    name: /app/prod/first_boot
    value: "{{ ansible_date_time.iso8601 }}"
    overwrite_value: never
    region: us-east-1
  delegate_to: localhost

- name: Remove a parameter
  git_cgallagher.aws.ssm_parameter:
    name: /app/prod/old_flag
    state: absent
    account: '123456789012'
    role_name: ParamWriter
    region: us-west-2
  delegate_to: localhost
"""

RETURN = r"""
parameter_metadata:
  description: Metadata of the parameter after the change. Empty when the parameter does not exist. The value is never returned.
  returned: always
  type: dict
  contains:
    name:
      description: Parameter name.
      type: str
      returned: when the parameter exists
      sample: /app/prod/db/password
    type:
      description: Parameter type.
      type: str
      returned: when the parameter exists
      sample: SecureString
    version:
      description: Parameter version.
      type: int
      returned: when the parameter exists
      sample: 3
    arn:
      description: Parameter ARN.
      type: str
      returned: when the parameter exists
      sample: arn:aws:ssm:us-west-2:123456789012:parameter/app/prod/db/password
    description:
      description: Parameter description.
      type: str
      returned: when the parameter exists
      sample: Production database password
    tier:
      description: Parameter tier.
      type: str
      returned: when the parameter exists
      sample: Standard
    key_id:
      description: KMS key of a SecureString parameter.
      type: str
      returned: when the parameter is a SecureString
      sample: alias/aws/ssm
    last_modified_date:
      description: When the parameter was last modified, ISO 8601.
      type: str
      returned: when the parameter exists
      sample: '2026-11-01T17:30:00+00:00'
"""

from ansible.module_utils.basic import AnsibleModule, missing_required_lib
from ansible.module_utils.common.text.converters import to_native

from ansible_collections.git_cgallagher.aws.plugins.module_utils import sts

try:
    import botocore.exceptions
except ImportError:
    pass  # handled by sts.HAS_BOTO3


def _get_existing(client, name):
    try:
        param = client.get_parameter(Name=name, WithDecryption=True)["Parameter"]
    except botocore.exceptions.ClientError as e:
        if sts.error_code(e) == "ParameterNotFound":
            return None
        raise
    details = client.describe_parameters(ParameterFilters=[{"Key": "Name", "Values": [name]}]).get("Parameters", [])
    detail = details[0] if details else {}
    param["Description"] = detail.get("Description")
    param["Tier"] = detail.get("Tier")
    param["KeyId"] = detail.get("KeyId")
    return param


def _metadata(param):
    if not param:
        return {}
    modified = param.get("LastModifiedDate")
    meta = {
        "name": param.get("Name"),
        "type": param.get("Type"),
        "version": param.get("Version"),
        "arn": param.get("ARN"),
        "description": param.get("Description"),
        "tier": param.get("Tier"),
        "last_modified_date": modified.isoformat() if modified is not None else None,
    }
    if param.get("KeyId"):
        meta["key_id"] = param["KeyId"]
    return meta


def _differs(existing, p):
    if existing["Value"] != p["value"] or existing["Type"] != p["string_type"]:
        return True
    if p["description"] is not None and (existing.get("Description") or "") != p["description"]:
        return True
    if p["tier"] and existing.get("Tier") != p["tier"]:
        return True
    if p["key_id"] and existing.get("KeyId") != p["key_id"]:
        return True
    return False


def _put(client, p, existing):
    kwargs = {"Name": p["name"], "Value": p["value"], "Type": p["string_type"]}
    if p["description"] is not None:
        kwargs["Description"] = p["description"]
    elif existing and existing.get("Description"):
        kwargs["Description"] = existing["Description"]
    if p["key_id"]:
        kwargs["KeyId"] = p["key_id"]
    if p["tier"]:
        kwargs["Tier"] = p["tier"]
    if existing:
        kwargs["Overwrite"] = True
    client.put_parameter(**kwargs)


def main():
    argument_spec = dict(
        name=dict(type="str", required=True),
        value=dict(type="str", no_log=True),
        string_type=dict(type="str", default="String", choices=["String", "StringList", "SecureString"]),
        description=dict(type="str"),
        key_id=dict(type="str", no_log=False),
        tier=dict(type="str", choices=["Standard", "Advanced", "Intelligent-Tiering"]),
        overwrite_value=dict(type="str", default="changed", choices=["never", "changed", "always"]),
        state=dict(type="str", default="present", choices=["present", "absent"]),
    )
    argument_spec.update(sts.role_argument_spec(session_name_default="ansible-ssm-parameter"))

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_if=[("state", "present", ("value",))],
    )
    p = module.params

    if not sts.HAS_BOTO3:
        module.fail_json(msg=missing_required_lib("boto3 and botocore"))

    role_opts = dict((name, p[name]) for name in sts.ROLE_OPTIONS)
    try:
        sts.validate_role_options(role_opts)
        session = sts.chained_session(role_opts)
        client = sts.make_client(session, "ssm", p["region"], p["endpoint_url"])
    except sts.StsError as e:
        module.fail_json(msg=to_native(e))

    try:
        existing = _get_existing(client, p["name"])

        if p["state"] == "absent":
            if existing is None:
                module.exit_json(changed=False, parameter_metadata={})
            if not module.check_mode:
                client.delete_parameter(Name=p["name"])
            module.exit_json(changed=True, parameter_metadata={})

        if existing is not None:
            if p["overwrite_value"] == "never":
                module.exit_json(changed=False, parameter_metadata=_metadata(existing), msg="Parameter exists and overwrite_value is never.")
            if p["overwrite_value"] == "changed" and not _differs(existing, p):
                module.exit_json(changed=False, parameter_metadata=_metadata(existing))

        if module.check_mode:
            predicted = dict(existing or {}, Name=p["name"], Type=p["string_type"])
            if p["description"] is not None:
                predicted["Description"] = p["description"]
            if p["tier"]:
                predicted["Tier"] = p["tier"]
            if p["key_id"]:
                predicted["KeyId"] = p["key_id"]
            module.exit_json(changed=True, parameter_metadata=_metadata(predicted))

        _put(client, p, existing)
        module.exit_json(changed=True, parameter_metadata=_metadata(_get_existing(client, p["name"])))
    except (botocore.exceptions.ClientError, botocore.exceptions.BotoCoreError) as e:
        module.fail_json(msg="SSM request for parameter %s failed: %s" % (p["name"], to_native(e)))


if __name__ == "__main__":
    main()
