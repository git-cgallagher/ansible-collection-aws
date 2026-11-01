# Security policy

## Reporting a vulnerability

Please report security issues **privately** through GitHub:
[Report a vulnerability](https://github.com/git-cgallagher/ansible-collection-aws/security/advisories/new)
(the **Security** tab, then **Report a vulnerability**). Don't open a public issue for a security problem.

You can expect an acknowledgement within a week. This is a one-person project, so fixes are best effort.

## Supported versions

Only the latest release gets fixes.

## Scope

The `ssm_parameter` lookup reads secrets with whatever AWS credentials and role your playbook
gives it. In scope:

- how it handles the credentials it is given and the assumed role credentials it caches (in
  process memory only, never written to disk or logged);
- leaking parameter values, for example in error messages or warnings;
- building the wrong role ARN, or assuming a role the caller didn't ask for.

Vulnerabilities in boto3, botocore, AWS STS or SSM themselves belong with AWS.

## A note on secrets in playbooks

A lookup's result is an ordinary variable. Use `no_log: true` on tasks that set or use
SecureString values, and keep them out of `debug` output.
