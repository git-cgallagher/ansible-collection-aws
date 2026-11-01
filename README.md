# git_cgallagher.aws

AWS automation for Ansible that works across accounts.

An SSM Parameter Store lookup and module that **assume an IAM role** before reading or writing, so
one controller can manage parameters in many AWS accounts by passing `account`, `role_name` and
`region`. Both can **chain through intermediate roles** (`via_role_arns`) for controllers that reach
spoke accounts through a hub role. The `amazon.aws.ssm_parameter` lookup and module only use the
credentials they are given and can't assume a role, let alone a chain, per task.

## Included content

| Name | Type | Description |
|------|------|-------------|
| `git_cgallagher.aws.ssm_parameter` | lookup | Get SSM Parameter Store values, optionally through an assumed IAM role |
| `git_cgallagher.aws.ssm_parameter` | module | Create, update or delete SSM Parameter Store parameters, optionally through an assumed IAM role |

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

# Through a hub role first, for a controller that can't assume the spoke role directly
- ansible.builtin.debug:
    msg: >-
      {{ lookup('git_cgallagher.aws.ssm_parameter', '/app/db/host',
                via_role_arns=['arn:aws:iam::999999999999:role/Hub'],
                account='123456789012', role_name='ParamReader', region='us-east-1') }}

# Writing: the module takes the same role options
- git_cgallagher.aws.ssm_parameter:
    name: /app/prod/db/password
    value: "{{ new_password }}"
    string_type: SecureString
    description: Rotated by Ansible
    tags: {app: billing, env: prod}
    via_role_arns: ['arn:aws:iam::999999999999:role/Hub']
    account: '123456789012'
    role_name: ParamWriter
    region: us-east-1
  delegate_to: localhost
  no_log: true
```

Every option is in `ansible-doc -t lookup git_cgallagher.aws.ssm_parameter` and
`ansible-doc -t module git_cgallagher.aws.ssm_parameter`, and
[`examples/cross_account_ssm.yml`](examples/cross_account_ssm.yml) is a full playbook.

### Options at a glance

Shared by the lookup and the module:

| Option | Purpose |
|--------|---------|
| `account` + `role_name` | Role to assume; the ARN is built as `arn:<partition>:iam::<account>:role/<role_name>` |
| `role_arn` | Full role ARN, instead of `account` + `role_name` |
| `via_role_arns` | Roles to assume first, in order (hub → spoke). Chained sessions are capped at one hour by AWS, so `duration_seconds` must be ≤ 3600 |
| `region` | Region for SSM and STS (falls back to `AWS_REGION`, then `AWS_DEFAULT_REGION`) |
| `external_id`, `role_session_name`, `duration_seconds` | Passed to `sts:AssumeRole` |
| `partition` | Override the partition (worked out from `region` by default: `cn-*`, `us-gov-*`, …) |
| `profile` / `access_key` + `secret_key` (+ `session_token`) | Base credentials used to assume the role; the default boto3 chain otherwise |
| `endpoint_url`, `sts_endpoint_url` | VPC or custom endpoints |
| `decrypt` | Decrypt SecureStrings (default `true`) |
| `bypath`, `recursive`, `shortnames`, `droppath` | Return everything under a path as a dictionary |
| `on_missing`, `on_denied` | `error` (default), `skip` or `warn` |

Module only:

| Option | Purpose |
|--------|---------|
| `name`, `value`, `string_type` | The parameter; `value` is required with `state: present` and never returned |
| `description`, `key_id`, `tier` | Optional parameter attributes; an existing description is kept when `description` isn't set |
| `overwrite_value` | `changed` (default): write only when value, type, description, tier or key differ; `never`; `always` |
| `state` | `present` (default) or `absent` |
| `tags`, `purge_tags` | Tags as a dictionary; set on create, reconciled on update without a new version. `purge_tags` (default `true`) removes tags not listed; leave `tags` unset to keep existing tags |

### Credential caching

The lookup caches assumed role credentials in the controller process for their lifetime (refreshed
five minutes before expiry), one entry per hop, keyed by the identity assuming it, role, session
name, external ID and duration. A loop over 500 hosts in the same account makes one
`sts:AssumeRole` call, not 500, and with `via_role_arns` one hub session serves every spoke. The
module runs in its own process per task and assumes the chain each time.

### IAM

The base credentials need `sts:AssumeRole` on the target role (or on the first role in
`via_role_arns`, and each role in the chain on the next). For the lookup the target role needs:

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

The module additionally needs `ssm:PutParameter`, `ssm:DescribeParameters` and, for `state: absent`,
`ssm:DeleteParameter`; only when `tags` is set, `ssm:ListTagsForResource`, `ssm:AddTagsToResource` and
`ssm:RemoveTagsFromResource`; plus `kms:Encrypt` on the key for SecureStrings.

## What this doesn't do (yet)

- Parameter policies (expiration, no-change notifications).
- Reading a parameter's history.

## Testing

CI runs `ansible-test` sanity, units and integration on ansible-core 2.18–2.21, plus yamllint,
ansible-lint and a build check. The unit and integration tests run against
[moto](https://github.com/getmoto/moto), so no AWS account is involved; they check that assuming
the role (or the chain) really reads from and writes to the other account. See `AGENTS.md` for the
commands.

## License

MIT. See [LICENSE](LICENSE).
