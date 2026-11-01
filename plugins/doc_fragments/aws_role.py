# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Chris Gallagher
# MIT License (see LICENSE or https://opensource.org/licenses/MIT)

from __future__ import absolute_import, division, print_function

__metaclass__ = type


class ModuleDocFragment(object):
    # Role assumption and credential options shared by the collection's plugins.
    # Keep in step with module_utils/sts.py (ROLE_OPTIONS and role_argument_spec).
    DOCUMENTATION = r"""
options:
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
  via_role_arns:
    description:
      - Roles to assume on the way to the target role, in order, for controllers that can't assume the target
        directly (for example a hub role that the spoke accounts trust).
      - Each entry is a full role ARN. The target role (O(role_arn), or O(account) and O(role_name)) is assumed
        last, from the credentials of the final entry.
      - AWS limits a session obtained with role-chained credentials to one hour, so O(duration_seconds) cannot
        exceed 3600 when this is set. O(external_id) applies to the target role only.
    type: list
    elements: str
  role_session_name:
    description:
      - Session name used for every C(sts:AssumeRole) call. Shows up in CloudTrail.
    type: str
  external_id:
    description:
      - External ID to pass to C(sts:AssumeRole) for the target role, if its trust policy requires one.
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
      - AWS region to query, and the region used for the STS calls.
    type: str
    aliases: [aws_region]
  profile:
    description:
      - Named profile from the AWS shared config to use as the base credentials.
      - Mutually exclusive with O(access_key), O(secret_key) and O(session_token).
    type: str
    aliases: [aws_profile]
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
"""
