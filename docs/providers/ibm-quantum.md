# IBM Quantum

QuantumD has an existing governed IBM execution path and a planned
portable path.

## Current managed path

The current organization-managed workflow uses:

- IBM Quantum access for backend discovery and execution.
- Google Secret Manager for the IBM credential.
- Google Cloud KMS for governed signing.
- Signed planning, approval, submission, and execution evidence.

This path remains available and must not be weakened by local-development
features.

## Phase 5B portable path

Phase 5B will add a GCP-free workflow for developers using WSL or another
trusted local environment.

Planned commands include:

~~~text
quantumd provider add ibm
quantumd provider test ibm
quantumd provider list

quantumd trust create
quantumd trust import
quantumd trust list
~~~

These commands are not documented as available until implementation and
acceptance testing are complete.

## Planned separation of responsibility

The IBM credential will authenticate access to IBM Quantum.

The QuantumD signing identity will authorize the exact governed plan,
approval, submission, and execution.

Possessing an IBM credential alone will not bypass QuantumD policy.
