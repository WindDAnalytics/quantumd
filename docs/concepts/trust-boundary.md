# Trust boundary

QuantumD treats code generation and governed execution as different
security domains.

~~~text
UNTRUSTED OR EXTERNAL                QUANTUMD TRUST BOUNDARY

AI-generated code  ────────────────> Project verification
Notebook changes  ────────────────> Policy evaluation
User configuration ───────────────> Exact workload binding
                                     Signed evidence
                                     Authorized execution
                                     Independent verification
~~~

## What crosses the boundary

A project crosses the boundary only after QuantumD establishes the exact
identity of its source, manifest, target, and execution parameters.

## What does not cross automatically

- A generated circuit is not automatically trusted.
- A passing simulation is not hardware authorization.
- A local signing key is not an organization-managed identity.
- An IBM credential is not approval to submit every workload.
- A completed job is not accepted until its result is evidence-bound.

## Fail-closed behavior

Missing, mismatched, expired, replayed, or corrupted evidence causes
denial instead of best-effort execution.
