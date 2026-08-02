# Security Policy

QuantumD treats execution integrity, evidence authenticity, authorization
binding, and hardware-access boundaries as security-critical behavior.

## Supported versions

QuantumD is currently an alpha project.

| Version | Supported |
| --- | --- |
| 0.7.4a0 | Yes |
| Earlier alpha releases | No |

Security fixes may require users to upgrade to the newest alpha release.

## Reporting a vulnerability

Do not disclose suspected vulnerabilities in a public GitHub issue,
Discussion, pull request, or social post.

Use GitHub private vulnerability reporting from the repository's **Security**
tab after it is enabled for the public launch. Include:

- the affected QuantumD version
- the operating system and Python version
- the trust mode involved
- the command or workflow that triggered the issue
- the expected security boundary
- the observed behavior
- a minimal reproduction, when safe
- whether credentials, evidence, or hardware access may have been exposed

Do not include live tokens, private keys, cloud credentials, IBM credentials,
or confidential evidence in the report.

## Security-sensitive areas

Reports are especially important when they involve:

- unsigned evidence being accepted
- approval replay or substitution
- workload, circuit, job, or result substitution
- mismatched execution identifiers
- invalid evidence chains being reported as verified
- local-development trust authorizing remote hardware
- unexpected IBM, KMS, or network contact
- private-key exposure or unsafe file permissions
- secret disclosure in logs, receipts, reports, or exceptions
- release artifacts that do not match their source or tag

## Scope boundaries

Local-development trust is restricted to simulator-only workflows. It is not
a substitute for organization-controlled signing, production authorization,
or remote hardware governance.

QuantumD alpha software must not be treated as the sole control protecting
safety-critical, classified, regulated, or financially material operations.

## Disclosure process

The maintainer will validate the report, determine affected versions, develop
a correction, and coordinate disclosure when appropriate. Public disclosure
should occur only after users have a reasonable opportunity to upgrade.
