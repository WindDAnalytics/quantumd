# Installation

QuantumD supports Python 3.10, 3.11, and 3.12 on Linux, Windows Subsystem for
Linux, Google Cloud Shell, and other compatible Python environments. Python
3.12 is the reference release environment.

## Fastest installation

Install the complete QuantumD package from production PyPI:

~~~bash
python -m pip install quantumd
~~~

QuantumD does not require you to create a virtual environment. It installs into
the Python environment associated with the `python` command.

For a reproducible alpha evaluation, pin the release:

~~~bash
python -m pip install "quantumd==0.7.5a0"
~~~

Confirm the command is available:

~~~bash
quantumd --help
~~~

## Install without manually managing an environment

On a system that protects its system Python, use `pipx`:

~~~bash
pipx install quantumd
~~~

or `uv tool`:

~~~bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv python install 3.12
uv tool install --python 3.12 quantumd
~~~

Both tools manage isolation behind the scenes and expose the `quantumd`
command on your user path.

## Optional dedicated environment

A dedicated environment is optional but remains useful for explicit dependency
isolation:

~~~bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv python install 3.12
uv venv --python 3.12 --seed ~/.venvs/quantumd-alpha
source ~/.venvs/quantumd-alpha/bin/activate
python -m pip install "quantumd==0.7.5a0"
~~~

## Run and verify the first governed workflow

~~~bash
quantumd quickstart my-first-quantumd-project
quantumd doctor my-first-quantumd-project
quantumd verify-chain my-first-quantumd-project --latest
~~~

The local path requires no Google Cloud account and no IBM Quantum account. It
must report local simulator-only trust, KMS configuration `False`, and hardware
authorization `PROHIBITED`. Independent verification must report no IBM, KMS,
or hardware action.

## Inspect the exact release artifact

Download only the current wheel:

~~~bash
python -m pip download \
  --no-deps \
  --only-binary=:all: \
  "quantumd==0.7.5a0"
sha256sum quantumd-0.7.5a0-py3-none-any.whl
~~~

Production PyPI displays the SHA-256 digest and publishing attestation for each
release file. Compare the local digest with the file details for
`quantumd 0.7.5a0` before installing a separately downloaded artifact.

~~~bash
python -m pip install ./quantumd-0.7.5a0-py3-none-any.whl
~~~

The authorized GitHub Actions workflow publishes through PyPI Trusted
Publishing with short-lived OIDC credentials. No PyPI password or long-lived
API token is stored in GitHub.

## WSL and older Linux distributions

Older WSL distributions may provide Python older than 3.10. Do not replace
`/usr/bin/python3`. Use `uv tool install --python 3.12 quantumd`, or use the
optional dedicated `uv` environment above.

## Troubleshooting

### `externally-managed-environment`

Use `pipx install quantumd` or `uv tool install --python 3.12 quantumd`.

### `quantumd: command not found`

~~~bash
python -m pip show quantumd
python -m site --user-base
~~~

Ensure the corresponding user binary directory is on `PATH`.

### A dependency fails while compiling

On Ubuntu or Debian:

~~~bash
sudo apt-get update
sudo apt-get install -y build-essential
~~~

Then rerun the installation.

## Install from source for development

~~~bash
git clone https://github.com/WindDAnalytics/quantumd.git
cd quantumd
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv python install 3.12
uv venv --python 3.12 --seed .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest -q
bash scripts/public_alpha_acceptance.sh
~~~

See [Platform support](platform-support.md) for the current verification matrix
and support boundaries.
