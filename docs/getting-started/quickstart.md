# Local quickstart

`quantumd quickstart` creates and executes a complete locally governed
simulator workflow.

Install the published alpha first by following the
[installation guide](installation.md).

## Run it

~~~bash
quantumd quickstart ./quantumd-first-run --shots 128
~~~

QuantumD will:

1. initialize a project
2. create a project-local P-256 signing identity
3. evaluate verification and policy gates
4. authorize only `aer-simulator`
5. execute the verified workload
6. sign the verification evidence and execution receipt
7. verify the resulting chain offline

A successful run ends with:

~~~text
[STATUS] QUANTUMD LOCAL QUICKSTART COMPLETE
Trust mode:             LOCAL_DEVELOPMENT
Trust scope:            LOCAL_SIMULATION_ONLY
Hardware authorization: PROHIBITED
KMS signing used:       False
IBM contacted:          False
Hardware action:        None
~~~

## Inspect the trust posture

~~~bash
quantumd doctor ./quantumd-first-run
~~~

The expected local posture is:

~~~text
Active trust mode:      LOCAL_DEVELOPMENT
KMS key configured:     False
Local identity valid:   True
Local trust scope:      LOCAL_SIMULATION_ONLY
Hardware authorization: PROHIBITED
~~~

## Verify the chain

~~~bash
quantumd verify-chain ./quantumd-first-run --latest
~~~

The verifier checks signatures, key lineage, authorization, source and
manifest identities, workload binding, circuit identities, the result hash,
shot count, and execution timing.

The verifier performs no IBM or KMS calls for a local chain.

## Local identity

The private identity is project-local and excluded from Git. QuantumD stores
it beneath:

~~~text
.quantumd/local-trust/
~~~

Partial, corrupted, or mismatched identity state is rejected rather than
silently repaired. A local identity cannot authorize IBM hardware.
