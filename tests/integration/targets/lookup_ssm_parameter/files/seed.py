#!/usr/bin/env python
# MIT License (see LICENSE or https://opensource.org/licenses/MIT)
"""Seed SSM parameters in the base account and in a second account, through moto."""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import sys

import boto3

REGION = "us-east-1"
TARGET_ACCOUNT = "222222222222"


def main(endpoint):
    base = boto3.client("ssm", region_name=REGION, endpoint_url=endpoint)
    base.put_parameter(Name="/base/greeting", Value="hello from base", Type="String")

    sts = boto3.client("sts", region_name=REGION, endpoint_url=endpoint)
    creds = sts.assume_role(
        RoleArn="arn:aws:iam::%s:role/seed" % TARGET_ACCOUNT,
        RoleSessionName="seed",
    )["Credentials"]
    target = boto3.client(
        "ssm",
        region_name=REGION,
        endpoint_url=endpoint,
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
    )
    target.put_parameter(Name="/app/prod/db/password", Value="hunter2", Type="SecureString")
    target.put_parameter(Name="/app/prod/db/host", Value="db.internal", Type="String")
    target.put_parameter(Name="/app/prod/port", Value="5432", Type="String")
    target.put_parameter(Name="/app/prod/hosts", Value="a,b,c", Type="StringList")


if __name__ == "__main__":
    main(sys.argv[1])
