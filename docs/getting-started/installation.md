# Installation

QuantumD runs on Linux, Windows Subsystem for Linux, Cloud Shell, and other
compatible Python environments.

The public alpha requires Python 3.10 or newer. Python 3.12 is the reference
environment used by the release and acceptance workflows.

## Install the published alpha

Create an isolated environment:

~~~bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
~~~

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

Because the wheel is installed from a local file, its dependencies resolve
from the default Python Package Index rather than TestPyPI.

!!! warning "Do not use TestPyPI as the only dependency index"

    Avoid `using TestPyPI as the sole package index`. TestPyPI is
    a testing service and may contain unrelated or incomplete dependency
    packages. Download the exact QuantumD artifact first, then install the
    local wheel.

Confirm the installation:

~~~bash
quantumd --help
~~~

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

From a WSL terminal:

~~~bash
cd ~

python3.12 -m venv quantumd-alpha
source quantumd-alpha/bin/activate
python -m pip install --upgrade pip

python -m pip download \
  --no-deps \
  --only-binary=:all: \
  --index-url https://test.pypi.org/simple/ \
  quantumd==0.7.4a0

python -m pip install \
  ./quantumd-0.7.4a0-py3-none-any.whl

quantumd quickstart ~/quantumd-first-run
~~~

## Install from source for development

Clone the repository only when contributing or evaluating unreleased changes:

~~~bash
git clone https://github.com/WindDAnalytics/quantumd.git
cd quantumd

python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
~~~

Run the development acceptance checks:

~~~bash
python -m pytest -q
bash scripts/public_alpha_acceptance.sh
~~~
