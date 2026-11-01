# AGENTS.md — ansible-collection-aws

> Read `~/Code/AGENTS.md` first (workspace-wide rules). This file covers only
> this repo.

## What this is

Public Ansible collection **`git_cgallagher.aws`** (MIT): AWS automation that
works across accounts. One plugin so far:

- `plugins/lookup/ssm_parameter.py` — reads SSM Parameter Store values,
  optionally after `sts:AssumeRole` into a role built from `account` +
  `role_name` (or a full `role_arn`). Exists because
  `amazon.aws.ssm_parameter` can't assume a role per lookup.

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

- Options are declared in the plugin's `DOCUMENTATION` and read with
  `self.get_option()`; `ansible-test sanity` (validate-modules) checks the
  docs. Add or change an option in the docs, `_validate_options`, the README
  table and the tests together.
- Assumed credentials live in the module-level `_CRED_CACHE`, keyed by base
  access key, role ARN, session name, external ID and duration. Anything new
  that changes which session STS returns must join the key.
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
- **The integration target starts moto on a random free port** and passes
  it in as `moto_endpoint`; the lookup reaches it through `endpoint_url` and
  `sts_endpoint_url`.
