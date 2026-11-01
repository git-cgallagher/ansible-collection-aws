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

The module also runs on a **real remote host** in the Molecule scenario
`tests/integration/molecule/ssm_parameter` (CI job `molecule ssm_parameter`,
a required check since 2026-11-01), on the shared `molecule-git-cgallagher`
driver like the other git_cgallagher collections. `node1`, a `python:3.13-slim`
container reached over the docker connection, writes a SecureString through
the Hub → ParamWriter chain into moto, which runs in a second container
(`motoserver/moto:5.2.5`) on a shared Docker network. boto3 lives in a venv
only `node1` has (`/opt/aws`), and `node1`'s `ansible_python_interpreter`
points into it, so the module can only have run there, whatever the
controller image contains. It checks:
- idempotence: a second converge changes nothing.
- in check mode through the chain: the same value is unchanged, while a
  different value or `state: absent` would change.
- in check mode with the base credentials, the same value would change, so
  the parameter only exists in the target account.
- the value never appears in a result.

The integration targets cover the lookup; lookups run on the controller, so
the scenario doesn't repeat them.

## Conventions

- **Every CI job sets `timeout-minutes`** (2026-11-01): GitHub's default is 6
  hours, and a stalled install or image pull would hold the runner that long.
  15 minutes per job (30 for `molecule`), several times their slowest green run
  (2.9 min). A new job needs one too.
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
- Tags: `PutParameter` accepts `Tags` only on create (AWS and moto both
  reject `Overwrite` + `Tags` with a ValidationException), so an existing
  parameter's tags go through `AddTagsToResource`/`RemoveTagsFromResource`
  and a tags-only change writes no new version.
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

Tool versions come from the ansible-runtime image that `RUNTIME_IMAGE` in
`.github/workflows/ansible-test.yml` pins (its shared dependency model): CI's
lint, build and Molecule jobs run in it, and `release.yml` installs
ansible-core from its `constraints.txt`. Only the ansible-test matrix picks
its own versions. Outside the image, use the same pins:

```bash
export RUNTIME_IMAGE=$(sed -n 's/^  RUNTIME_IMAGE: //p' .github/workflows/ansible-test.yml)
docker run --rm "$RUNTIME_IMAGE" cat /usr/share/ansible-runtime/constraints.txt > /tmp/constraints.txt
pip install -c /tmp/constraints.txt ansible-core ansible-lint yamllint -r requirements.txt \
  -r tests/unit/requirements.txt -r tests/integration/requirements.txt

# what CI runs
ansible-test sanity --docker default        # or --venv --python 3.13
ansible-test units --docker default         # or: python -m pytest tests/unit
ansible-test integration --docker default   # or --local (needs moto[server])
yamllint . && ansible-lint                  # or: .github/ci/runtime.sh ansible-lint

# the Molecule scenario, exactly as CI runs it: in the ansible-runtime image
# (driver included), from tests/integration. Needs Docker, nothing else.
export RUNTIME_IMAGE=$(sed -n 's/^  RUNTIME_IMAGE: //p' .github/workflows/ansible-test.yml)
(cd tests/integration && ../../.github/ci/runtime.sh molecule test -s ssm_parameter)
# step by step: one container for all the steps (see Gotchas)
(cd tests/integration && ../../.github/ci/runtime.sh bash -c \
  'molecule create -s ssm_parameter && molecule converge -s ssm_parameter; molecule destroy -s ssm_parameter')

# build the tarball
ansible-galaxy collection build --force
```

## ⚠️ Gotchas

- **Each `runtime.sh` call is a fresh container**, and Molecule keeps a
  scenario's state (its instance config) under `~/.ansible/tmp` inside it. So
  `molecule create`, then a separate `molecule prepare` call, finds no
  instances and falls back to SSH ("Could not resolve hostname node1"). Run
  single steps together in one `runtime.sh bash -c '…'` (Commands), or use
  `molecule test` as CI does. Learned 2026-11-01.
- **The Molecule scenario has no base config on purpose.** The version gate
  counts `.config/` as shipped, so `.config/molecule/config.yml` would force a
  release. Everything lives in the scenario's `molecule.yml`, and
  `.github/ci/runtime.sh` links the checkout in as `git_cgallagher.aws` under
  `collections/`, which `.gitignore` and `build_ignore` already cover, rather
  than isc's `.molecule-collections/`, which `build_ignore` doesn't.
- **moto's image runs the server as its entrypoint**
  (`moto_server -H 0.0.0.0`, port 5000), so its platform sets
  `override_command: false`. Without it, the docker kind's default command
  (`sleep infinity`) is passed to moto_server as arguments.
- **`ansible.builtin.pip` needs the `packaging` library on the target**, and
  `python:3.13-slim` doesn't have it, so the scenario's prepare runs
  `python -m pip` instead (learned writing the scenario, 2026-11-01).
- **`node1`'s interpreter is the venv the scenario's prepare builds**
  (`/opt/aws/bin/python`), so `prepare.yml` sets `ansible_python_interpreter`
  back to the image's `/usr/local/bin/python3` for itself. A task that runs on
  `node1` before the venv exists, outside that play, fails because the
  interpreter is missing. The controller image used to prove the same thing by
  having no boto3, but `ansible-runtime` 0.4.0 adds boto3 to both its targets.
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
- **`tests/integration/requirements.txt` deliberately avoids `moto[server]`.**
  That extra pulls in cfn-lint, aws-sam-translator and openapi-spec-validator;
  on 2026-11-01 a new release of one of them sent pip backtracking through
  Python 2 era packages under ansible-test's constraints and the integration
  job died in `pip install`. `moto[ssm,sts]` + `flask` + `flask-cors` is all
  `moto_server` needs here (proven for put/get/tags/STS through the server).
- **The module has no unit tests on purpose.** Patching module args
  portably across ansible-core 2.18–2.21 (`_ANSIBLE_ARGS` vs
  `patch_module_args`) isn't worth it; the integration target covers it
  end to end against moto.
- **No ansible-core devel testing, on purpose** (owner, 2026-11-01): CI
  tests the stable releases in its matrix only. The last devel sanity run (in
  a venv, aws run 41352740327) flagged `missing-gplv3-license` on both MIT
  plugins, which 2.18–2.21 don't, so check for it when a newer stable joins
  the matrix.

## TODO

- Nothing open.
