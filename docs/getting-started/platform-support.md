# Platform support

QuantumD is Python software, but a successful public installation also depends
on the operating system, Python bootstrap method, package architecture, and
native build tools.

The support labels below distinguish tested behavior from expected behavior.

## Current matrix

| Platform | Status | Installation path | Notes |
|---|---|---|---|
| WSL2 with Ubuntu 20.04 x86_64 | Verified manually | `uv` with Python 3.12 | Default Python 3.8 is unsupported. The `python3.12-venv` package may be unavailable. |
| Ubuntu 20.04 x86_64 container | CI verified | Public bootstrap | Tested through a container because GitHub retired its hosted Ubuntu 20.04 runner image. |
| Ubuntu 22.04 x86_64 | CI verified | Public bootstrap | Full wheel verification, quickstart, doctor, and chain verification. |
| Ubuntu 24.04 x86_64 | CI verified | Standard CI and public acceptance | Reference hosted Linux environment. |
| Google Cloud Shell | Verified | Existing Python 3.12 environment | Used for development and release acceptance. |
| Other x86_64 Linux distributions | Expected to work | `uv` with Python 3.12 | Not all package managers and libc versions are tested. |
| macOS | Not yet verified | Manual installation only | Do not interpret Linux CI as macOS support evidence. |
| Native Windows PowerShell or Command Prompt | Not yet supported | Use WSL2 | Current commands and verification scripts are designed for a POSIX shell. |
| Linux ARM64 | Not yet verified | Manual installation only | Binary dependency availability has not been accepted. |

## Python versions

QuantumD package metadata requires Python 3.10 or newer.

The project tests:

- Python 3.10
- Python 3.11
- Python 3.12

Python 3.12 is the reference environment for published-alpha acceptance.

Python 3.13 and newer are not yet part of the accepted compatibility matrix.

## What the compatibility checks prove

The public-install checks require:

- creation of an isolated Python environment
- download of the exact TestPyPI QuantumD wheel
- SHA-256 verification of the wheel
- dependency installation from the default Python Package Index
- CLI availability
- governed local quickstart completion
- `LOCAL_DEVELOPMENT` trust
- `LOCAL_SIMULATION_ONLY` scope
- explicit hardware prohibition
- independent evidence-chain verification
- confirmation that IBM and KMS were not contacted

They do not prove:

- support for every Linux distribution
- support for native Windows
- compatibility with every Python package combination
- hardware authorization from local-development trust
- production suitability for regulated or safety-critical systems

## Report a compatibility problem

Open a GitHub issue for reproducible installation failures and include:

- operating system and version
- architecture
- WSL version, when applicable
- `python --version`
- `uv --version`, when used
- the failing command
- the error text with credentials and private paths removed

Do not publish tokens, private keys, cloud identifiers, confidential workloads,
or sensitive evidence.
