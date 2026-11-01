# git_cgallagher.aws

AWS automation for Ansible that works across accounts.

The first plugin is an SSM Parameter Store lookup that **assumes an IAM role** before reading, so
one controller can pull parameters from many AWS accounts by passing `account`, `role_name` and
`region`. The `amazon.aws.ssm_parameter` lookup only uses the credentials it is given and can't
assume a role per lookup.

## Included content

| Name | Type | Description |
|------|------|-------------|
| `git_cgallagher.aws.ssm_parameter` | lookup | Get SSM Parameter Store values, optionally through an assumed IAM role |

## Requirements

- ansible-core 2.18 or newer
- `boto3` and `botocore` on the controller (`pip install -r requirements.txt`)

## Installation

```bash
ansible-galaxy collection install git_cgallagher.aws
```

Or in `requirements.yml`:

```yaml
collections:
  - name: git_cgallagher.aws
```

## Usage

```yaml
# Same account as the controller's credentials
- ansible.builtin.debug:
    msg: "{{ lookup('git_cgallagher.aws.ssm_parameter', '/app/db/host', region='us-east-1') }}"

# Another account: assumes arn:aws:iam::123456789012:role/ParamReader first
- ansible.builtin.set_fact:
    db_password: >-
      {{ lookup('git_cgallagher.aws.ssm_parameter', '/app/db/password',
                account='123456789012', role_name='ParamReader', region='us-west-2') }}
  no_log: true

# Per-host account and region from inventory
- ansible.builtin.debug:
    msg: >-
      {{ lookup('git_cgallagher.aws.ssm_parameter', '/platform/' ~ inventory_hostname ~ '/token',
                account=aws_account_id, role_name='AnsibleParamReader', region=aws_region) }}

# Everything under a path as a dictionary
- ansible.builtin.set_fact:
    app_config: >-
      {{ lookup('git_cgallagher.aws.ssm_parameter', '/app/prod/', bypath=true, recursive=true,
                shortnames=true, account='123456789012', role_name='ParamReader',
                region='eu-west-1') }}
```

Every option is in `ansible-doc -t lookup git_cgallagher.aws.ssm_parameter`, and
[`examples/cross_account_ssm.yml`](examples/cross_account_ssm.yml) is a full playbook.

### Options at a glance

| Option | Purpose |
|--------|---------|
| `account` + `role_name` | Role to assume; the ARN is built as `arn:<partition>:iam::<account>:role/<role_name>` |
| `role_arn` | Full role ARN, instead of `account` + `role_name` |
| `region` | Region for SSM and STS (falls back to `AWS_REGION`, then `AWS_DEFAULT_REGION`) |
| `external_id`, `role_session_name`, `duration_seconds` | Passed to `sts:AssumeRole` |
| `partition` | Override the partition (worked out from `region` by default: `cn-*`, `us-gov-*`, …) |
| `profile` / `access_key` + `secret_key` (+ `session_token`) | Base credentials used to assume the role; the default boto3 chain otherwise |
| `endpoint_url`, `sts_endpoint_url` | VPC or custom endpoints |
| `decrypt` | Decrypt SecureStrings (default `true`) |
| `bypath`, `recursive`, `shortnames`, `droppath` | Return everything under a path as a dictionary |
| `on_missing`, `on_denied` | `error` (default), `skip` or `warn` |

### Credential caching

Assumed role credentials are cached in the controller process for their lifetime (refreshed five
minutes before expiry), keyed by base identity, role, session name, external ID and duration.
A loop over 500 hosts in the same account makes one `sts:AssumeRole` call, not 500.

### IAM

The base credentials need `sts:AssumeRole` on the target role. The target role needs:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["ssm:GetParameter", "ssm:GetParametersByPath"],
      "Resource": "arn:aws:ssm:*:123456789012:parameter/app/*"
    },
    {
      "Effect": "Allow",
      "Action": "kms:Decrypt",
      "Resource": "arn:aws:kms:*:123456789012:key/<key-id>"
    }
  ]
}
```

## What this doesn't do (yet)

- Role chaining (hub role, then a spoke role) for controllers that can't assume the target role
  directly.
- Writing parameters. It's a lookup; use `amazon.aws.ssm_parameter` (the module) to write.

## Testing

CI runs `ansible-test` sanity, units and integration on ansible-core 2.18–2.21, plus yamllint,
ansible-lint and a build check. The unit and integration tests run against
[moto](https://github.com/getmoto/moto), so no AWS account is involved; they check that assuming
the role really reads from the other account. See `AGENTS.md` for the commands.

## License

MIT. See [LICENSE](LICENSE).
