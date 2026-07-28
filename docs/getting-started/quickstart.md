# Local quickstart

`quantumd quickstart` creates and executes a complete locally governed
simulator workflow.

## Run it

~~~bash
quantumd quickstart ./quantumd-first-run --shots 128
~~~

QuantumD will:

1. Initialize a project.
2. Create a project-local P-256 signing identity.
3. Run verification and policy gates.
4. Authorize only `aer-simulator`.
5. Execute the verified workload.
6. Sign the evidence and execution receipt.
7. Verify the evidence chain offline.

## Inspect the trust posture

~~~bash
quantumd doctor ./quantumd-first-run
~~~

The expected local posture is:

~~~text
Active trust mode:      LOCAL_DEVELOPMENT
Local trust scope:      LOCAL_SIMULATION_ONLY
Hardware authorization: PROHIBITED
~~~

## Verify the chain

~~~bash
quantumd verify-chain ./quantumd-first-run --latest
~~~

The verifier performs no network calls for a local chain.

## Local identity

The private identity is project-local and excluded from Git. QuantumD
stores it beneath:

~~~text
.quantumd/local-trust/
~~~

Do not manually replace individual identity files. Partial or mismatched
identity state is rejected rather than silently repaired.
