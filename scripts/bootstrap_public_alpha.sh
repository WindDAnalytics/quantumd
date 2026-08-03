#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="0.7.4a0"
WHEEL="quantumd-0.7.4a0-py3-none-any.whl"
EXPECTED_SHA256="761a865a5aaf655f570fa3ae6f1d0f9b1b09cb89ee5519ac1843b738d251b7d2"

VENV="${QUANTUMD_BOOTSTRAP_VENV:-$HOME/.venvs/quantumd-alpha}"
PROJECT="${QUANTUMD_BOOTSTRAP_PROJECT:-$HOME/quantumd-first-run}"
PROJECT_EXPLICIT="false"
SKIP_QUICKSTART="false"
FORCE="false"

usage() {
    cat <<'EOF'
Usage:
  bash scripts/bootstrap_public_alpha.sh [options]

Options:
  --venv PATH          Virtual environment location.
  --project PATH       Quickstart project location.
  --skip-quickstart    Install and verify the CLI without running a project.
  --force              Recreate an existing virtual environment.
  -h, --help           Show this help text.

Environment variables:
  QUANTUMD_BOOTSTRAP_VENV
  QUANTUMD_BOOTSTRAP_PROJECT
EOF
}

fail() {
    echo
    echo "BOOTSTRAP FAILED: $1" >&2
    exit 1
}

section() {
    echo
    echo "------------------------------------------------------"
    echo "$1"
    echo "------------------------------------------------------"
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --venv)
            [ "$#" -ge 2 ] || fail "--venv requires a path."
            VENV="$2"
            shift 2
            ;;
        --project)
            [ "$#" -ge 2 ] || fail "--project requires a path."
            PROJECT="$2"
            PROJECT_EXPLICIT="true"
            shift 2
            ;;
        --skip-quickstart)
            SKIP_QUICKSTART="true"
            shift
            ;;
        --force)
            FORCE="true"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            fail "Unknown option: $1"
            ;;
    esac
done

echo "======================================================"
echo "QuantumD Public Alpha Bootstrap"
echo "======================================================"
echo "Package version: $VERSION"
echo "Environment:     $VENV"
echo "Project:         $PROJECT"

section "1. Checking the host"

[ "$(uname -s)" = "Linux" ] ||
    fail "This bootstrap currently supports Linux and WSL. See the installation guide for other platforms."

command -v curl >/dev/null 2>&1 ||
    fail "curl is required."
command -v sha256sum >/dev/null 2>&1 ||
    fail "sha256sum is required."

if grep -qi microsoft /proc/version 2>/dev/null; then
    echo "Host: WSL"
else
    echo "Host: Linux"
fi

if [ -n "${VIRTUAL_ENV:-}" ]; then
    echo "NOTICE: Another virtual environment is active:"
    echo "  $VIRTUAL_ENV"
    echo "This script does not modify or nest that environment."
fi

if ! command -v cc >/dev/null 2>&1; then
    echo
    echo "NOTICE: A C compiler was not detected."
    echo "If dependency installation fails while building crcmod, install"
    echo "your distribution's build tools. On Ubuntu or Debian:"
    echo
    echo "  sudo apt-get update"
    echo "  sudo apt-get install -y build-essential"
fi

section "2. Installing or locating uv"

if command -v uv >/dev/null 2>&1; then
    UV="$(command -v uv)"
else
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    command -v uv >/dev/null 2>&1 ||
        fail "uv installed but was not found on PATH."
    UV="$(command -v uv)"
fi

"$UV" --version

section "3. Installing the reference Python"

"$UV" python install 3.12
MANAGED_PYTHON="$("$UV" python find 3.12)"
"$MANAGED_PYTHON" --version

section "4. Creating the isolated environment"

if [ -e "$VENV" ]; then
    if [ "$FORCE" = "true" ]; then
        rm -rf "$VENV"
    elif [ ! -x "$VENV/bin/python" ]; then
        fail "$VENV exists but is not a usable virtual environment. Remove it or rerun with --force."
    else
        EXISTING_VERSION="$(
            "$VENV/bin/python" -c \
                'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
        )"
        [ "$EXISTING_VERSION" = "3.12" ] ||
            fail "$VENV uses Python $EXISTING_VERSION, not Python 3.12. Remove it or rerun with --force."
        echo "Reusing existing Python 3.12 environment."
    fi
fi

if [ ! -x "$VENV/bin/python" ]; then
    mkdir -p "$(dirname "$VENV")"
    "$UV" venv \
        --python 3.12 \
        --seed \
        "$VENV"
fi

PYTHON="$VENV/bin/python"
QUANTUMD="$VENV/bin/quantumd"

"$PYTHON" --version
"$PYTHON" -m pip --version

section "5. Downloading the exact public-alpha wheel"

ROOT="$(mktemp -d "${TMPDIR:-/tmp}/quantumd-bootstrap.XXXXXX")"
trap 'rm -rf "$ROOT"' EXIT

cd "$ROOT"

"$PYTHON" -m pip download \
    --disable-pip-version-check \
    --no-deps \
    --only-binary=:all: \
    --index-url https://test.pypi.org/simple/ \
    "quantumd==$VERSION"

[ -f "$WHEEL" ] ||
    fail "Expected wheel was not downloaded."

section "6. Verifying the published artifact"

printf '%s  %s\n' \
    "$EXPECTED_SHA256" \
    "$WHEEL" |
    sha256sum --check

section "7. Installing QuantumD"

"$PYTHON" -m pip install \
    --disable-pip-version-check \
    --upgrade \
    "./$WHEEL"

[ -x "$QUANTUMD" ] ||
    fail "QuantumD CLI was not installed."

"$QUANTUMD" --help >/dev/null
echo "PASS: QuantumD CLI is available."

if [ "$SKIP_QUICKSTART" = "true" ]; then
    echo
    echo "======================================================"
    echo "QUANTUMD PUBLIC ALPHA INSTALLATION COMPLETE"
    echo "======================================================"
    echo "Activate later with:"
    echo "  source \"$VENV/bin/activate\""
    exit 0
fi

section "8. Running the governed local workflow"

if [ -e "$PROJECT" ]; then
    if [ "$PROJECT_EXPLICIT" = "true" ]; then
        fail "Project path already exists: $PROJECT"
    fi
    PROJECT="${PROJECT}-$(date +%Y%m%d-%H%M%S)"
    echo "Default project already existed."
    echo "Using: $PROJECT"
fi

QUICKSTART_LOG="$ROOT/quickstart.log"
DOCTOR_LOG="$ROOT/doctor.log"
VERIFY_LOG="$ROOT/verify.log"

"$QUANTUMD" quickstart "$PROJECT" |
    tee "$QUICKSTART_LOG"

"$QUANTUMD" doctor "$PROJECT" |
    tee "$DOCTOR_LOG"

"$QUANTUMD" verify-chain "$PROJECT" --latest |
    tee "$VERIFY_LOG"

grep -F "LOCAL_DEVELOPMENT" "$DOCTOR_LOG" >/dev/null ||
    fail "Doctor did not report LOCAL_DEVELOPMENT."
grep -F "LOCAL_SIMULATION_ONLY" "$DOCTOR_LOG" >/dev/null ||
    fail "Doctor did not report LOCAL_SIMULATION_ONLY."
grep -F "Hardware authorization: PROHIBITED" "$DOCTOR_LOG" >/dev/null ||
    fail "Hardware was not explicitly prohibited."
grep -F "COMPLETE EVIDENCE CHAIN VERIFIED" "$VERIFY_LOG" >/dev/null ||
    fail "Independent chain verification did not complete."
grep -F "IBM contacted:   False" "$VERIFY_LOG" >/dev/null ||
    fail "Verification did not confirm IBM isolation."
grep -F "KMS contacted:   False" "$VERIFY_LOG" >/dev/null ||
    fail "Verification did not confirm KMS isolation."
grep -F "Hardware action: None" "$VERIFY_LOG" >/dev/null ||
    fail "Verification reported a hardware action."

echo
echo "======================================================"
echo "QUANTUMD PUBLIC ALPHA BOOTSTRAP PASSED"
echo "======================================================"
echo "Environment: $VENV"
echo "Project:     $PROJECT"
echo "Activate later with:"
echo "  source \"$VENV/bin/activate\""
