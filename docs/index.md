---
title: Governed Quantum Execution
description: Verify every workload. Control every execution. Prove every result.
---

<div class="quantumd-hero" markdown>

<div class="quantumd-kicker">Governed quantum execution</div>

# Trust every quantum run.

QuantumD verifies quantum workloads, enforces execution policy, signs
evidence, and independently verifies what actually ran.

[Start locally](getting-started/quickstart.md){ .md-button .md-button--primary }
[Explore the trust model](concepts/trust-modes.md){ .md-button }

<div class="quantumd-terminal">
$ quantumd quickstart<br>
[1/6] Project initialization................ PASS<br>
[2/6] Simulator-only local identity......... PASS<br>
[3/6] Verification and policy gates......... PASS<br>
[4/6] Governed Aer execution................ PASS<br>
[5/6] Signed evidence and trust scope....... PASS<br>
[6/6] Offline chain verification............ PASS
</div>

**Runs locally · No GCP required · No quantum hardware contacted**

</div>

<div class="quantumd-proof">
  <span class="pass">32 TESTS PASSED</span>
  <span class="pass">LOCAL CHAIN VERIFIED</span>
  <span class="deny">HARDWARE AUTHORITY PROHIBITED</span>
  <span>KMS CONTACTED: FALSE</span>
  <span>IBM CONTACTED: FALSE</span>
</div>

## AI can generate quantum code. QuantumD makes execution accountable.

QuantumD places a verification and governance boundary between generated
software and quantum execution.

The system binds authorization to the exact project, source, manifest,
backend, shot count, circuit, result artifact, and execution receipt.

## Start locally

The current public repository supports a source installation and a
simulator-only governed quickstart:

~~~bash
git clone https://github.com/WindDAnalytics/quantumd.git
cd quantumd

python -m venv .venv
source .venv/bin/activate
python -m pip install -e .

quantumd quickstart
~~~

The local workflow creates a project-local signing identity and uses the
Aer simulator. It does not require a GCP account.

## Evidence, not assertions

Local development produces a compact evidence graph:

~~~text
PROJECT ──> QVERIFY ──> QEXEC
~~~

Organization-governed hardware execution extends that chain:

~~~text
PROJECT
   │
   ▼
QVERIFY ──> QPLAN ──> QAPPROVAL ──> QSUB ──> QEXEC
~~~

Each node is bound to its predecessor and can be checked independently.

## Trust modes

| Mode | Status | Hardware |
|---|---|---|
| `LOCAL_DEVELOPMENT` | Available | Prohibited |
| `KMS_GOVERNED` | Available for the existing managed path | Policy controlled |
| `SELF_MANAGED_HARDWARE` | Phase 5B | Planned |
| `UNCONFIGURED` | Denied | Prohibited |

!!! info "Current versus planned"

    QuantumD runs locally today without GCP. GCP-free IBM hardware
    execution, encrypted local IBM credentials, and imported signing
    identities are Phase 5B deliverables.

## The trust boundary

<div class="quantumd-boundary" markdown>

Generated code remains outside the trusted boundary until QuantumD
verifies the project, applies policy, and creates signed evidence.

A local-development identity cannot be promoted into hardware authority.

</div>
