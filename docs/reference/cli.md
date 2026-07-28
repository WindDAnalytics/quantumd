# CLI commands

## Available local commands

### `quantumd quickstart`

Creates and executes a complete simulator-only governed project.

~~~bash
quantumd quickstart [PROJECT_PATH] --shots 128
~~~

### `quantumd doctor`

Reports installation readiness, simulator availability, trust mode,
identity validity, and hardware authority.

~~~bash
quantumd doctor [PROJECT_PATH]
~~~

### `quantumd verify-chain`

Independently verifies the latest or selected evidence chain.

~~~bash
quantumd verify-chain [PROJECT_PATH] --latest
~~~

## Existing managed commands

QuantumD also includes governed verification, planning, approval,
submission, reconciliation, chain inspection, and adversarial testing
workflows used by the current KMS-governed path.

Consult `quantumd --help` and each command's `--help` output for the
exact interface in the installed version.

## Planned Phase 5B commands

The following interface is directional and not yet a released contract:

~~~text
quantumd provider add|test|list|remove
quantumd trust create|import|list
~~~
