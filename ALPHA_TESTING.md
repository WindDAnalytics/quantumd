# QuantumD Alpha Evaluation

QuantumD is recruiting five early technical evaluators to test whether a
stranger can understand, install, run, and assess the execution-integrity
model without founder assistance.

## Evaluator profiles

The initial group should include:

1. a quantum developer
2. a software-supply-chain or security engineer
3. an ML, data, or scientific-computing engineer
4. a technical leader from an audit-exposed environment
5. an educator, researcher, or advanced technical student

## Evaluation rule

Complete the installation and quickstart without a live walkthrough. Record
where the documentation creates confusion, skepticism, or unnecessary work.

## Secure public-alpha installation

Use the [installation guide](docs/getting-started/installation.md). The
recommended Linux and WSL path is the repository bootstrap:

```bash
curl -fsSLO \
  https://raw.githubusercontent.com/WindDAnalytics/quantumd/main/scripts/bootstrap_public_alpha.sh

less bootstrap_public_alpha.sh
bash bootstrap_public_alpha.sh
```

The evaluator should review the script before running it. The bootstrap creates
an isolated Python 3.12 environment, verifies the exact public wheel, runs the
local quickstart, and independently verifies the resulting evidence.

Record the operating system, architecture, Python bootstrap method, installation
time, and time to the first verified chain.

## Expected security boundary

The local quickstart should report:

```text
Trust mode:             LOCAL_DEVELOPMENT
Trust scope:            LOCAL_SIMULATION_ONLY
Hardware authorization: PROHIBITED
KMS signing used:       False
IBM contacted:          False
Hardware action:        None
```

Independent verification should end with:

```text
[STATUS] COMPLETE EVIDENCE CHAIN VERIFIED
IBM contacted:   False
KMS contacted:   False
Hardware action: None
```

## Feedback questions

Please report:

1. How long did installation take?
2. How long until the first verified chain?
3. Where did you become confused?
4. Which claim felt least credible?
5. Could you explain the Evidence Graph in your own words?
6. Could you explain the local trust boundary?
7. What existing tool did QuantumD remind you of?
8. What real workflow would you test next?
9. What evidence would an auditor or reviewer need?
10. Would you continue evaluating QuantumD? Why or why not?

## What not to share

Do not include:

- live credentials
- private keys
- cloud account identifiers
- IBM tokens
- confidential workloads
- sensitive evidence
- regulated or classified information

## Submit feedback

After completing the evaluation, open the repository's **Alpha evaluation
feedback** issue form. Do not include credentials, private keys, cloud account
identifiers, confidential workloads, or sensitive evidence.
