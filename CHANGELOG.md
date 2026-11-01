# Changelog

## 0.1.0 — 2026-11-01

First release.

- New lookup `git_cgallagher.aws.ssm_parameter`: reads SSM Parameter Store
  values, optionally after assuming an IAM role given as `account` +
  `role_name` (or `role_arn`) and `region`. Supports `external_id`, session
  name and duration, partitions, profiles or explicit base keys, VPC
  endpoints for SSM and STS, `bypath` reads, and `on_missing`/`on_denied`
  handling. Assumed credentials are cached per role for the run.
