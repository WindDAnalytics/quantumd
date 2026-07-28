# Local simulation

Local simulation is the safest way to begin with QuantumD.

## Create a governed project

~~~bash
quantumd quickstart ./my-quantumd-project --shots 128
~~~

## Diagnose the environment

~~~bash
quantumd doctor ./my-quantumd-project
~~~

## Verify the latest execution

~~~bash
quantumd verify-chain ./my-quantumd-project --latest
~~~

## Security properties

In `LOCAL_DEVELOPMENT` mode:

- The only permitted target is `aer-simulator`.
- IBM is not contacted.
- KMS is not contacted.
- No hardware action is taken.
- Evidence is signed locally.
- Verification can be completed offline.

Local evidence is educational and developmental evidence. It is not a
substitute for organization-managed production authorization.
