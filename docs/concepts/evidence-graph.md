# Evidence graph

The Evidence Graph is the durable record of governed execution.

## Local graph

~~~text
QVERIFY ──> QEXEC
~~~

`QVERIFY` records the verified project and executable authorization.
`QEXEC` records the executed circuit, backend, shots, result artifact,
and receipt.

## Managed hardware graph

~~~text
QVERIFY
   │
   ▼
QPLAN ──> QAPPROVAL ──> QSUB ──> IBM JOB ──> QEXEC
~~~

## Core bindings

The verifier checks that:

- Cryptographic signatures are valid.
- The signing-key lineage is consistent.
- Authorization binds to the exact verification record.
- Source and manifest identities have not changed.
- Execution binds to the authorized workload.
- Logical and executed circuit identities match the evidence.
- The result artifact hash is correct.
- Observed shots equal authorized shots.
- Authorization predates execution.

The graph is intended to be verifiable independently of the system that
originally produced it.
