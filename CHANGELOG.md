# Changelog

## Unreleased
### Public installation hardening
- Added a guided Linux and WSL bootstrap using a `uv`-managed Python 3.12 environment.
- Added explicit platform-support labels and a compatibility matrix.
- Documented Ubuntu 20.04 default-Python and missing-`venv` failure modes.
- Added compatibility testing for Python 3.10, 3.11, and 3.12.
- Added public bootstrap acceptance for Ubuntu 22.04 and Ubuntu 20.04 in a container.

## 0.7.4a0 - 2026-08-02

### Public-alpha acceptance hardening

- Added a reusable wheel-installed public-alpha acceptance gate.
- Builds QuantumD from tracked source and installs the wheel into an isolated runtime.
- Confirms the package resolves from `site-packages` rather than an editable checkout.
- Preserves fail-closed denial when governed execution lacks KMS-signed evidence.
- Runs the local quickstart under isolated and deliberately poisoned cloud credentials.
- Requires simulator-only local trust and prohibits hardware authorization.
- Validates the generated QVERIFY and QEXEC evidence contracts.
- Independently verifies all cryptographic, workload, circuit, result, shot, and timing bindings.
- Confirms IBM and KMS are not contacted during offline local verification.
- Requires local private-key permissions and generated `.gitignore` protection.
- Requires the acceptance process to leave the repository unchanged.
