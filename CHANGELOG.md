# Changelog

## 0.2.0 — 2026-11-01

- New module `git_cgallagher.aws.ssm_parameter`: creates, updates and
  deletes Parameter Store parameters with the same role options as the
  lookup (`account` + `role_name` or `role_arn`, `via_role_arns`,
  `external_id`, endpoints, profiles or explicit keys). `overwrite_value`
  (`never`, `changed`, `always`), `description`, `key_id`, `tier`, check
  mode; returns metadata only, never the value.
- Role chaining: the new `via_role_arns` option on the lookup and the module
  assumes intermediate roles (a hub role, say) before the target role.
  Intermediate hops use one-hour sessions; `duration_seconds` above 3600 is
  rejected when chaining, as AWS requires. The lookup caches each hop, so one
  hub session serves every spoke behind it.
- Shared code moved to `plugins/module_utils/sts.py`, and the shared options
  into the `aws_role` doc fragment. No behaviour change for existing lookups.

## 0.1.0 — 2026-11-01

First release.

- New lookup `git_cgallagher.aws.ssm_parameter`: reads SSM Parameter Store
  values, optionally after assuming an IAM role given as `account` +
  `role_name` (or `role_arn`) and `region`. Supports `external_id`, session
  name and duration, partitions, profiles or explicit base keys, VPC
  endpoints for SSM and STS, `bypath` reads, and `on_missing`/`on_denied`
  handling. Assumed credentials are cached per role for the run.
