# Contributing to QuantumD

QuantumD welcomes focused contributions that strengthen governed execution,
verification, reproducibility, evidence integrity, documentation, and safe
developer onboarding.

## Development setup

Use Python 3.12 for the reference development environment.

```bash
git clone https://github.com/WindDAnalytics/quantumd.git
cd quantumd

curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

uv python install 3.12
uv venv --python 3.12 --seed .venv
source .venv/bin/activate

python -m pip install -e ".[dev]"
```

Contributors who already have Python 3.12 and working standard-library virtual
environment support may use `python3.12 -m venv .venv`.

Run the regression suite:

```bash
python -m compileall -q src tests
python -m pytest -q
```

Run the built-wheel public acceptance gate:

```bash
bash scripts/public_alpha_acceptance.sh
```

Build the documentation:

```bash
python -m pip install -r requirements-docs.txt
mkdocs build --strict
```

## Contribution rules

- Create a focused branch from current `main`.
- Keep each pull request limited to one coherent change.
- Add or update tests for behavioral changes.
- Preserve fail-closed behavior.
- Do not weaken cryptographic, authorization, or evidence bindings.
- Do not introduce network or hardware access into ordinary tests.
- Do not include credentials, tokens, private keys, generated identities, or
  confidential evidence.
- Use exact commit SHAs for third-party GitHub Actions.
- Keep local-development trust simulator-only.
- Document new public commands and evidence fields.

## Security-critical changes

Changes involving signing, authorization, approvals, submissions, receipts,
evidence verification, trust selection, hardware access, or release workflows
must explain:

1. the trust boundary before the change
2. the trust boundary after the change
3. the failure behavior
4. the adversarial or regression tests added
5. any new network, identity, or credential dependency

## Pull-request acceptance

A pull request should not be considered ready until:

- tests pass
- documentation builds strictly
- built distributions validate
- the public-alpha wheel gate passes
- the repository remains clean after acceptance
- no sensitive information is introduced
