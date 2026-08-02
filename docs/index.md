---
title: Governed Quantum Execution
description: Verify every workload. Control every execution. Prove every result.
---

<div class="quantumd-hero" markdown>

<div class="quantumd-kicker">Governed quantum execution</div>

# Trust every quantum run.

QuantumD verifies quantum workloads, enforces execution policy, signs
evidence, and independently verifies what actually ran.

[Install the alpha](getting-started/installation.md){ .md-button .md-button--primary }
[Run the quickstart](getting-started/quickstart.md){ .md-button }
[Explore the trust model](concepts/trust-modes.md){ .md-button }

<div class="quantumd-terminal">
$ quantumd quickstart my-first-quantumd-project<br>
[1/6] Project initialization................ PASS<br>
[2/6] Simulator-only local identity......... PASS<br>
[3/6] Verification and policy gates......... PASS<br>
[4/6] Governed Aer execution................ PASS<br>
[5/6] Signed evidence and trust scope....... PASS<br>
[6/6] Offline chain verification............ PASS
</div>

**Runs locally · No GCP required · No IBM account required · Hardware prohibited**

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

## Install the public alpha

Create an isolated environment, download the exact QuantumD wheel from
TestPyPI, verify its checksum, and install the local artifact:

~~~bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip

python -m pip download \
  --no-deps \
  --only-binary=:all: \
  --index-url https://test.pypi.org/simple/ \
  quantumd==0.7.4a0

echo \
  "761a865a5aaf655f570fa3ae6f1d0f9b1b09cb89ee5519ac1843b738d251b7d2  quantumd-0.7.4a0-py3-none-any.whl" \
  | sha256sum --check

python -m pip install \
  ./quantumd-0.7.4a0-py3-none-any.whl
~~~

Run the local governed workflow:

~~~bash
quantumd quickstart my-first-quantumd-project
~~~

## Evidence, not assertions

Local development produces a compact Evidence Graph:

~~~text
PROJECT -> QVERIFY -> QEXEC
~~~

Organization-governed hardware execution extends that chain:

~~~text
PROJECT
   |
   v
QVERIFY -> QPLAN -> QAPPROVAL -> QSUB -> IBM JOB -> QEXEC
~~~

Each node is bound to its predecessor and can be checked independently.

## Trust modes

| Mode | Status | Hardware |
| --- | --- | --- |
| `LOCAL_DEVELOPMENT` | Available | Prohibited |
| `KMS_GOVERNED` | Available for the organization-managed path | Policy controlled |
| `SELF_MANAGED_HARDWARE` | Planned | Not yet available |
| `UNCONFIGURED` | Denied | Prohibited |

!!! info "Local evaluation is intentionally restricted"

    QuantumD runs locally without GCP or IBM credentials. Local-development
    trust is simulator-only and cannot be promoted into hardware authority.

## Evaluate the alpha

QuantumD is recruiting five early technical evaluators. Complete the
installation and quickstart without a live walkthrough, then report where the
experience became confusing, unconvincing, or unnecessarily difficult.

[Read the evaluation guide](alpha-evaluation.md){ .md-button .md-button--primary }
