# Installation

QuantumD runs on Linux, Windows Subsystem for Linux, Google Cloud Shell, and
other compatible Python environments.

The public alpha requires Python 3.10 or newer. Python 3.12 is the reference
environment used by release and acceptance workflows.

## Recommended environment setup

Use `uv` when the computer does not already have a supported Python and working
virtual-environment support. This is the recommended path for WSL and for older
Linux distributions.

Install `uv` for the current user:

~~~bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
~~~

Install the reference Python and create one dedicated environment:

~~~bash
uv python install 3.12
uv venv --python 3.12 --seed ~/.venvs/quantumd-alpha
source ~/.venvs/quantumd-alpha/bin/activate
python --version
~~~

Expected Python output begins with `Python 3.12`.

For later terminal sessions, do not recreate the environment. Activate the same
one:

~~~bash
source ~/.venvs/quantumd-alpha/bin/activate
~~~

!!! note "Already have Python 3.10 or newer?"
    You may use the standard library instead:

    ~~~bash
    python3 -m venv ~/.venvs/quantumd-alpha
    source ~/.venvs/quantumd-alpha/bin/activate
    python -m pip install --upgrade pip
    ~~~

    If environment creation fails or the available Python is older than 3.10,
    use the recommended `uv` path.

## Install the published alpha

Download only the exact QuantumD wheel from TestPyPI:

~~~bash
python -m pip download \
  --no-deps \
  --only-binary=:all: \
  --index-url https://test.pypi.org/simple/ \
  quantumd==0.7.4a0
~~~

Verify the published wheel:

~~~bash
echo \
  "761a865a5aaf655f570fa3ae6f1d0f9b1b09cb89ee5519ac1843b738d251b7d2  quantumd-0.7.4a0-py3-none-any.whl" \
  | sha256sum --check
~~~

Install the downloaded wheel:

~~~bash
python -m pip install \
  ./quantumd-0.7.4a0-py3-none-any.whl
~~~

Because the wheel is installed from a local file, its dependencies resolve from
the default Python Package Index rather than TestPyPI.

!!! warning "Do not use TestPyPI as the only dependency index"
    TestPyPI is a testing service and may contain unrelated or incomplete
    dependency packages. Download the exact QuantumD artifact first, verify its
    checksum, and then install the local wheel.

Confirm the installation:

~~~bash
quantumd --help
~~~

## Guided Linux and WSL bootstrap

The repository includes a bootstrap script that installs an isolated Python
3.12 environment, downloads the exact public-alpha wheel, verifies its SHA-256
digest, installs QuantumD, runs the local quickstart, and independently verifies
the evidence chain.

Download and review the script before running it:

~~~bash
curl -fsSLO \
  https://raw.githubusercontent.com/WindDAnalytics/quantumd/main/scripts/bootstrap_public_alpha.sh

less bootstrap_public_alpha.sh
bash bootstrap_public_alpha.sh
~~~

The script does not replace the operating system's Python. Its default
environment is `~/.venvs/quantumd-alpha`.

## Run the first governed workflow

~~~bash
quantumd quickstart my-first-quantumd-project
~~~

Then inspect and independently verify it:

~~~bash
quantumd doctor my-first-quantumd-project

quantumd verify-chain \
  my-first-quantumd-project \
  --latest
~~~

No Google Cloud account or IBM Quantum account is required for the local
simulator path.

## Windows Subsystem for Linux

Older WSL distributions may ship with an unsupported default Python. Ubuntu
20.04, for example, commonly provides Python 3.8. Installing a newer interpreter
through `apt` may still leave the matching `venv` package unavailable.

Use the recommended `uv` setup rather than replacing `/usr/bin/python3`.

If the terminal prompt appears nested, such as `((.venv))`, open a clean shell
and activate only the standard QuantumD environment:

~~~bash
exec bash
source ~/.venvs/quantumd-alpha/bin/activate
~~~

Repeated activation does not corrupt QuantumD, but it creates confusing shell
prompts.

## Troubleshooting

### `uv: command not found`

Add the user installation directory to the current shell:

~~~bash
export PATH="$HOME/.local/bin:$PATH"
~~~

To make that persistent in Bash:

~~~bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
~~~

### Python is older than 3.10

Do not modify the operating system's default Python. Use:

~~~bash
uv python install 3.12
uv venv --python 3.12 --seed ~/.venvs/quantumd-alpha
~~~

### `python3.12-venv` cannot be located

This can occur on older Ubuntu releases. Use the `uv` path instead of adding
more operating-system Python repositories.

### A dependency fails while compiling

One dependency may need standard build tools on some Linux systems. On Ubuntu
or Debian:

~~~bash
sudo apt-get update
sudo apt-get install -y build-essential
~~~

Then rerun the installation.

## Install from source for development

Clone the repository only when contributing or evaluating unreleased changes:

~~~bash
git clone https://github.com/WindDAnalytics/quantumd.git
cd quantumd

curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

uv python install 3.12
uv venv --python 3.12 --seed .venv
source .venv/bin/activate

python -m pip install -e ".[dev]"
~~~

Run the development acceptance checks:

~~~bash
python -m pytest -q
bash scripts/public_alpha_acceptance.sh
~~~

See [Platform support](platform-support.md) for the current verification matrix
and support boundaries.
