# Verify an evidence chain

Use the independent chain verifier to confirm that an execution remains
cryptographically and logically intact.

## Latest execution

~~~bash
quantumd verify-chain ./my-project --latest
~~~

## What success means

A successful verification establishes that:

- The required signatures validate.
- The signing lineage is internally consistent.
- Authorization and verification records refer to the same workload.
- The project source and manifest remain unchanged.
- The executed circuit and result remain bound to the receipt.
- The shot count and execution sequence satisfy policy.

## Offline local verification

Local projects cache the public key needed to verify their evidence.

The private signing key is not required to perform verification.

## Failure

Treat any failed check as an evidence-integrity incident. Do not modify
records to make them pass. Preserve the project and inspect the failing
node and its predecessor.
