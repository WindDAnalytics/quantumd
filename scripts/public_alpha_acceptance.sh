#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(
    git rev-parse --show-toplevel
)"
PYTHON="${PYTHON:-python3}"

ROOT="$(
    mktemp -d \
        "${TMPDIR:-/tmp}/quantumd-public-alpha.XXXXXX"
)"

SOURCE="$ROOT/source"
DIST="$ROOT/dist"
BUILD_VENV="$ROOT/build-venv"
RUNTIME_VENV="$ROOT/runtime-venv"
PROJECT="$ROOT/project"
ISOLATED_HOME="$ROOT/home"

QUICKSTART_LOG="$ROOT/quickstart.log"
DOCTOR_LOG="$ROOT/doctor.log"
CHAIN_LOG="$ROOT/chain.log"
VERIFY_LOG="$ROOT/verify-chain.log"

cleanup() {
    rm -rf "$ROOT"
}

trap cleanup EXIT

fail() {
    echo
    echo "PUBLIC ALPHA ACCEPTANCE FAILED: $1"
    exit 1
}

section() {
    echo
    echo "------------------------------------------------------"
    echo "$1"
    echo "------------------------------------------------------"
}

cd "$REPO_ROOT"

STATUS_BEFORE="$(
    git status \
        --porcelain=v1 \
        --untracked-files=all
)"

mkdir -p \
    "$SOURCE" \
    "$DIST" \
    "$ISOLATED_HOME"

section "1. Preparing isolated tracked source"

git ls-files -z |
    tar \
        --null \
        --files-from=- \
        --create \
        --file=- |
    tar \
        --extract \
        --file=- \
        --directory="$SOURCE"

[ -f "$SOURCE/pyproject.toml" ] ||
    fail "Tracked source copy is incomplete."

section "2. Building distribution wheel"

"$PYTHON" -m venv "$BUILD_VENV"

"$BUILD_VENV/bin/python" -m pip install \
    --disable-pip-version-check \
    --no-cache-dir \
    --quiet \
    --upgrade \
    pip setuptools wheel build

"$BUILD_VENV/bin/python" -m build \
    --wheel \
    --outdir "$DIST" \
    "$SOURCE"

mapfile -t WHEELS < <(
    find "$DIST" \
        -maxdepth 1 \
        -type f \
        -name 'quantumd-*.whl' \
        | sort
)

[ "${#WHEELS[@]}" -eq 1 ] ||
    fail "Expected exactly one QuantumD wheel."

WHEEL="${WHEELS[0]}"

echo "Wheel: $(basename "$WHEEL")"
sha256sum "$WHEEL"

section "3. Installing wheel into clean runtime"

"$PYTHON" -m venv "$RUNTIME_VENV"

"$RUNTIME_VENV/bin/python" -m pip install \
    --disable-pip-version-check \
    --no-cache-dir \
    --quiet \
    --upgrade \
    pip

"$RUNTIME_VENV/bin/python" -m pip install \
    --disable-pip-version-check \
    --no-cache-dir \
    --quiet \
    "$WHEEL"

section "4. Verifying installed package origin"

"$RUNTIME_VENV/bin/python" - <<PY
from importlib import metadata
from pathlib import Path
import tomllib
import quantumd

source_data = tomllib.loads(
    Path("$SOURCE/pyproject.toml").read_text(
        encoding="utf-8"
    )
)

expected = source_data["project"]["version"]
installed = metadata.version("quantumd")
module_path = Path(quantumd.__file__).resolve()

print(f"Expected version:  {expected}")
print(f"Installed version: {installed}")
print(f"Module path:       {module_path}")

if installed != expected:
    raise SystemExit(
        "Installed version does not match source version."
    )

if "site-packages" not in str(module_path):
    raise SystemExit(
        "QuantumD was not loaded from site-packages."
    )

if str(Path("$REPO_ROOT").resolve()) in str(module_path):
    raise SystemExit(
        "QuantumD resolved to the repository checkout."
    )

print("PASS: Installed wheel identity verified.")
PY

SANITIZED_ENV=(
    env -i
    "HOME=$ISOLATED_HOME"
    "PATH=$RUNTIME_VENV/bin:/usr/bin:/bin"
    "LANG=C.UTF-8"
    "LC_ALL=C.UTF-8"
    "PYTHONNOUSERSITE=1"
    "HTTP_PROXY=http://127.0.0.1:9"
    "HTTPS_PROXY=http://127.0.0.1:9"
    "ALL_PROXY=http://127.0.0.1:9"
    "http_proxy=http://127.0.0.1:9"
    "https_proxy=http://127.0.0.1:9"
    "all_proxy=http://127.0.0.1:9"
    "NO_PROXY=localhost,127.0.0.1"
)

section "5. Verifying unsigned governed execution fails closed"

set +e
UNSIGNED_OUTPUT="$(
    "${SANITIZED_ENV[@]}" \
        "$RUNTIME_VENV/bin/quantumd" \
            demo \
            --shots 32 \
        2>&1
)"
UNSIGNED_STATUS="$?"
set -e

printf '%s\n' "$UNSIGNED_OUTPUT"

[ "$UNSIGNED_STATUS" -ne 0 ] ||
    fail "Unsigned governed demonstration unexpectedly succeeded."

grep -F \
    "Evidence record is not signed." \
    <<< "$UNSIGNED_OUTPUT" \
    >/dev/null ||
    fail "Unsigned evidence denial reason was not reported."

grep -F \
    "[STATUS] EXECUTION DENIED: AUTHORIZATION_FAILED" \
    <<< "$UNSIGNED_OUTPUT" \
    >/dev/null ||
    fail "Unsigned execution did not fail at authorization."

if grep -Fq \
    "EXECUTION COMPLETED AND ATTESTED" \
    <<< "$UNSIGNED_OUTPUT"
then
    fail "Unsigned workload reached an attested completion state."
fi

echo "PASS: Unsigned governed execution failed closed."

section "6. Running poisoned-environment quickstart"

"${SANITIZED_ENV[@]}" \
    QUANTUMD_KMS_KEY_VERSION="projects/forbidden/locations/forbidden/keyRings/forbidden/cryptoKeys/forbidden/cryptoKeyVersions/1" \
    GOOGLE_APPLICATION_CREDENTIALS="$ROOT/credentials-must-not-be-used.json" \
    IBM_QUANTUM_TOKEN="must-not-be-used" \
    QISKIT_IBM_TOKEN="must-not-be-used" \
    IBM_TOKEN="must-not-be-used" \
    "$RUNTIME_VENV/bin/quantumd" \
        quickstart \
        "$PROJECT" \
        --name "QuantumD Public Alpha Acceptance" \
        --shots 32 \
    | tee "$QUICKSTART_LOG"

grep -F \
    "QUANTUMD LOCAL QUICKSTART COMPLETE" \
    "$QUICKSTART_LOG" \
    >/dev/null ||
    fail "Quickstart did not complete."

grep -F \
    "Trust mode:             LOCAL_DEVELOPMENT" \
    "$QUICKSTART_LOG" \
    >/dev/null ||
    fail "Quickstart did not use local trust."

grep -F \
    "Hardware authorization: PROHIBITED" \
    "$QUICKSTART_LOG" \
    >/dev/null ||
    fail "Hardware was not explicitly prohibited."

grep -F \
    "KMS signing used:       False" \
    "$QUICKSTART_LOG" \
    >/dev/null ||
    fail "Quickstart reported KMS signing."

grep -F \
    "IBM contacted:          False" \
    "$QUICKSTART_LOG" \
    >/dev/null ||
    fail "Quickstart did not confirm IBM isolation."

grep -F \
    "Hardware action:        None" \
    "$QUICKSTART_LOG" \
    >/dev/null ||
    fail "Quickstart reported a hardware action."

section "7. Verifying sanitized doctor state"

"${SANITIZED_ENV[@]}" \
    "$RUNTIME_VENV/bin/quantumd" \
        doctor \
        "$PROJECT" \
    | tee "$DOCTOR_LOG"

grep -F \
    "Active trust mode:      LOCAL_DEVELOPMENT" \
    "$DOCTOR_LOG" \
    >/dev/null ||
    fail "Doctor did not report local development trust."

grep -F \
    "KMS key configured:     False" \
    "$DOCTOR_LOG" \
    >/dev/null ||
    fail "Doctor detected inherited KMS configuration."

grep -F \
    "QUANTUMD ENVIRONMENT READY" \
    "$DOCTOR_LOG" \
    >/dev/null ||
    fail "Doctor did not report a ready environment."

section "8. Inspecting evidence graph"

"${SANITIZED_ENV[@]}" \
    "$RUNTIME_VENV/bin/quantumd" \
        chain \
        "$PROJECT" \
        --latest \
    | tee "$CHAIN_LOG"

grep -F \
    "QuantumD Local Evidence Graph" \
    "$CHAIN_LOG" \
    >/dev/null ||
    fail "Local evidence graph was not produced."

grep -F \
    "QVERIFY" \
    "$CHAIN_LOG" \
    >/dev/null ||
    fail "QVERIFY node is missing."

grep -F \
    "QEXEC" \
    "$CHAIN_LOG" \
    >/dev/null ||
    fail "QEXEC node is missing."

section "9. Independently verifying evidence"

"${SANITIZED_ENV[@]}" \
    "$RUNTIME_VENV/bin/quantumd" \
        verify-chain \
        "$PROJECT" \
        --latest \
    | tee "$VERIFY_LOG"

grep -F \
    "COMPLETE EVIDENCE CHAIN VERIFIED" \
    "$VERIFY_LOG" \
    >/dev/null ||
    fail "Independent chain verification failed."

grep -F \
    "IBM contacted:   False" \
    "$VERIFY_LOG" \
    >/dev/null ||
    fail "Verification did not confirm IBM isolation."

grep -F \
    "KMS contacted:   False" \
    "$VERIFY_LOG" \
    >/dev/null ||
    fail "Verification did not confirm KMS isolation."

grep -F \
    "Hardware action: None" \
    "$VERIFY_LOG" \
    >/dev/null ||
    fail "Verification reported a hardware action."

section "10. Inspecting generated evidence contracts"

"$RUNTIME_VENV/bin/python" - <<PY
from __future__ import annotations

import json
import stat
from pathlib import Path

project = Path("$PROJECT")

pointer = json.loads(
    (
        project
        / "evidence"
        / "latest.json"
    ).read_text(encoding="utf-8")
)

verification_path = project / pointer["record"]

verification = json.loads(
    verification_path.read_text(encoding="utf-8")
)

receipt_paths = list(
    (
        project
        / "evidence"
        / "executions"
    ).glob("QEXEC-*/receipt.json")
)

if len(receipt_paths) != 1:
    raise SystemExit(
        f"Expected one execution receipt, found "
        f"{len(receipt_paths)}."
    )

receipt_path = receipt_paths[0]

receipt = json.loads(
    receipt_path.read_text(encoding="utf-8")
)

expected_integrity = {
    "provider": "quantumd-local-development",
    "signature_status": "LOCAL_DEVELOPMENT_SIGNED",
    "hardware_authorization": "PROHIBITED",
}

for label, record in (
    ("QVERIFY", verification),
    ("QEXEC", receipt),
):
    integrity = record.get("integrity")

    if not isinstance(integrity, dict):
        raise SystemExit(
            f"{label} integrity metadata is missing."
        )

    for field, expected in expected_integrity.items():
        actual = integrity.get(field)

        if actual != expected:
            raise SystemExit(
                f"{label} {field} mismatch: "
                f"expected {expected!r}, "
                f"received {actual!r}."
            )

if (
    verification["integrity"]["key_version"]
    != receipt["integrity"]["key_version"]
):
    raise SystemExit(
        "QVERIFY and QEXEC signing lineage differs."
    )

target = receipt.get("target")

if not isinstance(target, dict):
    raise SystemExit(
        "Execution target metadata is missing."
    )

required_target = {
    "provider": "local",
    "backend": "aer-simulator",
}

for field, expected in required_target.items():
    actual = target.get(field)

    if actual != expected:
        raise SystemExit(
            f"Execution target {field} mismatch: "
            f"expected {expected!r}, "
            f"received {actual!r}."
        )

simulation_method = target.get("simulation_method")

if (
    simulation_method is not None
    and not isinstance(simulation_method, str)
):
    raise SystemExit(
        "Execution target simulation_method "
        "must be a string when present."
    )

if receipt.get("status") != "EXECUTION_COMPLETED":
    raise SystemExit(
        "Execution receipt is not completed."
    )

private_key = (
    project
    / ".quantumd"
    / "local-trust"
    / "private-key.pem"
)

mode = stat.S_IMODE(private_key.stat().st_mode)

if mode != 0o600:
    raise SystemExit(
        f"Local private-key mode is {oct(mode)}, "
        "expected 0o600."
    )

gitignore = (
    project / ".gitignore"
).read_text(encoding="utf-8")

if ".quantumd/local-trust/" not in gitignore:
    raise SystemExit(
        "Generated .gitignore does not protect "
        "the local private identity."
    )

print(f"QVERIFY: {verification_path}")
print(f"QEXEC:   {receipt_path}")
print("PASS: Generated evidence contracts verified.")
PY

section "11. Confirming repository stability"

STATUS_AFTER="$(
    git status \
        --porcelain=v1 \
        --untracked-files=all
)"

if [ "$STATUS_AFTER" != "$STATUS_BEFORE" ]; then
    echo "Repository state before:"
    printf '%s\n' "$STATUS_BEFORE"

    echo
    echo "Repository state after:"
    printf '%s\n' "$STATUS_AFTER"

    fail "Acceptance gate modified the repository."
fi

echo
echo "======================================================"
echo "PUBLIC ALPHA WHEEL ACCEPTANCE PASSED"
echo "======================================================"
echo "Wheel installation:     PASS"
echo "Unsigned fail-closed:    PASS"
echo "Local quickstart:       PASS"
echo "Cloud isolation:        PASS"
echo "Hardware prohibition:   PASS"
echo "Evidence graph:         PASS"
echo "Independent validation: PASS"
echo "Repository stability:   PASS"
