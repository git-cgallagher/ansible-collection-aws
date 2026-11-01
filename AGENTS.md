# AGENTS.md — ansible-collection-aws

> Read `~/Code/AGENTS.md` first (workspace-wide rules). This file covers only
> this repo.

## What this is

Public Ansible collection **`git_cgallagher.aws`** (MIT): AWS automation that
works across accounts.

- `plugins/lookup/ssm_parameter.py` — reads SSM Parameter Store values,
  optionally after `sts:AssumeRole` into a role built from `account` +
  `role_name` (or a full `role_arn`), chaining through `via_role_arns`
  first. Exists because `amazon.aws.ssm_parameter` can't assume a role per
  lookup.
- `plugins/modules/ssm_parameter.py` — creates, updates and deletes
  parameters with the same role options (0.2.0). Returns metadata, never the
  value.
- `plugins/module_utils/sts.py` — everything both share: option validation,
  role ARN building, the base session, `sts:AssumeRole` per hop, the
  per-hop credential cache (used by the lookup only; a module is a fresh
  process per task), `ROLE_OPTIONS` and `role_argument_spec()`.
- `plugins/doc_fragments/aws_role.py` — the shared options' docs. The
  lookup adds `env:` entries for `region` and `profile` and its own
  `role_session_name` default in its own `options:`; the fragment merge
  keeps both (checked with `ansible-doc`).

It's standalone on purpose: plain boto3/botocore, no dependency on
`amazon.aws` or its module_utils, so it doesn't break when that collection's
internals move.

## ⚠️ Maturity

Tested against moto only, never against real AWS in CI. Unit tests
(`tests/unit`) and the integration target
(`tests/integration/targets/lookup_ssm_parameter`) both rely on moto giving
an assumed role's credentials the role's account, so a parameter seeded
through a role in account B is invisible to the base credentials and visible
only through the lookup's role assumption. moto doesn't enforce IAM or trust
policies, so `on_denied` and AssumeRole failures are covered by unit tests
with mocked errors, not end to end.

## Conventions

- A shared role/credential option is declared in **four** places that must
  agree: the `aws_role` doc fragment, `sts.ROLE_OPTIONS`,
  `sts.role_argument_spec()` (a unit test checks these two match) and
  `sts.validate_role_options()`. Then the README table and the tests.
  `ansible-test sanity` (validate-modules) checks the module's docs against
  its argument_spec, and the lookup's docs against `get_option()` use.
- Assumed credentials live in the lookup's module-level `_CRED_CACHE`, one
  entry per hop, keyed by the assuming identity's access key, role ARN,
  session name, external ID and duration. Anything new that changes which
  session STS returns must join the key (in `sts.chained_session`).
- Role chaining: intermediate hops get a one-hour session and no external
  ID; the final hop gets `duration_seconds` and `external_id`.
  `duration_seconds` > 3600 with `via_role_arns` is rejected up front
  because AWS would reject the final hop anyway.
- The module never returns the parameter value (`parameter_metadata` only)
  and `value` is `no_log`. validate-modules insists on an explicit `no_log`
  for `access_key`, `secret_key`, `session_token` and `key_id`.
- Never put a parameter value in an exception, warning or `display` message.
  Names and ARNs are fine.
- Release flow mirrors `ansible-collection-windows` and
  `ansible-collection-isc`: every merge that changes shipped files must bump
  `galaxy.yml` + add a `CHANGELOG.md` entry (CI-enforced). After the merge's
  green `ansible-test` run on main, `release.yml` publishes to Galaxy and
  tags `v<version>`. `GALAXY_API_KEY` lives in the main-only `galaxy`
  environment. **Merge one PR at a time** and let its release run finish.

## Commands

`ansible-test` needs the checkout at `ansible_collections/git_cgallagher/aws/`.

```bash
pip install ansible-core ansible-lint yamllint -r requirements.txt \
  -r tests/unit/requirements.txt -r tests/integration/requirements.txt

# what CI runs
ansible-test sanity --docker default        # or --venv --python 3.13
ansible-test units --docker default         # or: python -m pytest tests/unit
ansible-test integration --docker default   # or --local (needs moto[server])
yamllint . && ansible-lint

# build the tarball
ansible-galaxy collection build --force
```

## ⚠️ Gotchas

- **boto3 doesn't read `AWS_REGION` in every version** (only
  `AWS_DEFAULT_REGION`). The plugin reads both itself through its `region`
  option's `env:` entries; don't remove them in favour of boto3's lookup.
  Helper scripts that call boto3 directly should pass `region_name`.
- **`tests/unit/conftest.py` sets up the collection loader only for plain
  pytest.** Under `ansible-test units` the loader already exists and the
  branch is skipped.
- **Each integration target starts moto on a random free port** and passes
  it in as `moto_endpoint`; the plugins reach it through `endpoint_url` and
  `sts_endpoint_url`. The module target sets `ansible_python_interpreter`
  to `ansible_playbook_python`, because the module runs through the `local`
  connection and the discovered interpreter may not have boto3.
- **No `key: value` text inside a plain YAML scalar in `DOCUMENTATION`.**
  `C(delegate_to: localhost)` in a description broke `ansible-doc` for the
  module ("could not find expected ':'"); say it in words instead.
- **The module has no unit tests on purpose.** Patching module args
  portably across ansible-core 2.18–2.21 (`_ANSIBLE_ARGS` vs
  `patch_module_args`) isn't worth it; the integration target covers it
  end to end against moto.
