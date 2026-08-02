# QuantumD

[![CI](https://github.com/WindDAnalytics/quantumd/actions/workflows/ci.yml/badge.svg)](https://github.com/WindDAnalytics/quantumd/actions/workflows/ci.yml)
[![Documentation](https://github.com/WindDAnalytics/quantumd/actions/workflows/docs.yml/badge.svg)](https://github.com/WindDAnalytics/quantumd/actions/workflows/docs.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-public%20alpha-orange.svg)](CHANGELOG.md)

> **QuantumD exists to produce trustworthy evidence, not favorable quantum results.**

QuantumD is the trust and execution layer for AI-generated quantum software.
It verifies the exact workload, enforces execution policy, binds authorization
to what actually runs, and produces evidence that can be checked independently.

AI may generate a circuit or computational workflow. QuantumD decides whether
that exact workload is permitted to execute and whether the resulting evidence
supports the claimed run.

## What QuantumD proves

QuantumD binds together:

- the project source and manifest
- the verification decision
- the authorized backend and shot count
- the logical and executed circuit identities
- the result artifact
- the execution receipt
- the signing-key lineage
- the order of authorization and execution

A successful job identifier or a complete cloud log is not enough. QuantumD
checks the chain connecting reviewer intent, authorization, execution, and
results.

## Run the public alpha

QuantumD `0.7.4a0` is published on TestPyPI. Use an isolated Python environment
and download only the QuantumD wheel from TestPyPI. Dependencies are then
resolved from the default Python Package Index.

```bash
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
```

Create and execute a governed local project:

```bash
quantumd quickstart my-first-quantumd-project
```

Inspect the trust posture and independently verify the evidence:

```bash
quantumd doctor my-first-quantumd-project

quantumd verify-chain \
  my-first-quantumd-project \
  --latest
```

The local quickstart is intentionally restricted:

```text
Trust mode:             LOCAL_DEVELOPMENT
Trust scope:            LOCAL_SIMULATION_ONLY
Hardware authorization: PROHIBITED
KMS signing used:       False
IBM contacted:          False
Hardware action:        None
```

Independent verification should finish with:

```text
[STATUS] COMPLETE EVIDENCE CHAIN VERIFIED
IBM contacted:   False
KMS contacted:   False
Hardware action: None
```

No Google Cloud account, IBM Quantum account, or hardware access is required
for the local quickstart.

## The Evidence Graph

A local simulator run produces a compact evidence chain:

```text
PROJECT -> QVERIFY -> QEXEC
```

An organization-governed hardware workflow extends the chain:

```text
PROJECT
   |
   v
QVERIFY -> QPLAN -> QAPPROVAL -> QSUB -> IBM JOB -> QEXEC
```

Each node binds to the exact records before and after it. Independent
verification checks signatures, key lineage, workload identity, circuit
identity, result hashes, shot counts, and execution timing without contacting
IBM or KMS.

## Trust modes

| Trust mode | Purpose | Hardware authority |
| --- | --- | --- |
| `UNCONFIGURED` | No valid signing provider | Prohibited |
| `LOCAL_DEVELOPMENT` | Project-local simulator evaluation | Prohibited |
| `KMS_GOVERNED` | Organization-managed authorization and signing | Policy controlled |
| `SELF_MANAGED_HARDWARE` | Planned developer-managed hardware path | Not yet available |

A local-development identity cannot be promoted into hardware authority.
Missing, mismatched, replayed, expired, or corrupted evidence causes denial.

## Evaluate QuantumD

QuantumD is recruiting five early evaluators:

1. a quantum developer
2. a software-supply-chain or security engineer
3. an ML, data, or scientific-computing engineer
4. a technical leader from an audit-exposed environment
5. an educator, researcher, or advanced technical student

Complete the installation and quickstart without a live walkthrough. Then
submit the structured **Alpha evaluation feedback** issue form.

Read [ALPHA_TESTING.md](ALPHA_TESTING.md) before beginning.

## Documentation

- [Installation](docs/getting-started/installation.md)
- [Local quickstart](docs/getting-started/quickstart.md)
- [Evidence Graph](docs/concepts/evidence-graph.md)
- [Trust boundary](docs/concepts/trust-boundary.md)
- [Trust modes](docs/concepts/trust-modes.md)
- [IBM Quantum provider](docs/providers/ibm-quantum.md)
- [CLI reference](docs/reference/cli.md)
- [Security policy](SECURITY.md)
- [Contributing](CONTRIBUTING.md)
- [Support](SUPPORT.md)

## Alpha boundaries

QuantumD is alpha software. Interfaces and evidence schemas may evolve.
Pin exact versions and preserve evidence with the version that produced it.

Local simulation is suitable for evaluation and development. QuantumD alpha
must not be treated as the sole control protecting safety-critical, classified,
regulated, or financially material operations.

Security concerns must be reported privately under [SECURITY.md](SECURITY.md).
Do not publish credentials, private keys, confidential workloads, or sensitive
evidence in issues or Discussions.

## Project

- Website: [quantumd.ai](https://quantumd.ai)
- License: [Apache License 2.0](LICENSE)
- Current alpha: `0.7.4a0`
- Release tag: `v0.7.4-alpha`
