# Installation

QuantumD can run in Linux, WSL, Cloud Shell, or another compatible Python
environment.

## Install from source

The public repository is the authoritative installation path before the
production PyPI alpha is released.

~~~bash
git clone https://github.com/WindDAnalytics/quantumd.git
cd quantumd

python -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -e .
~~~

Confirm the installation:

~~~bash
quantumd --help
quantumd doctor .
~~~

## WSL

No Google Cloud account is required for local simulation.

From a WSL terminal:

~~~bash
cd ~
git clone https://github.com/WindDAnalytics/quantumd.git
cd quantumd

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
~~~

You can then run:

~~~bash
quantumd quickstart ~/quantumd-first-run
~~~

## Public PyPI target

The intended public-alpha experience is:

~~~bash
pip install quantumd
quantumd quickstart
~~~

This documentation does not claim that production PyPI publishing has
occurred until the release acceptance process is complete.
