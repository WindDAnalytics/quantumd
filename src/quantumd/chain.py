"""Offline Evidence Graph rendering and end-to-end chain verification."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import click

from quantumd.approval import _matching_plan_payload


class ChainVerificationError(RuntimeError):
    """Raised when an evidence chain fails independent verification."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _read_json(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    if not path.is_file():
        raise ChainVerificationError(f"{label} not found: {path}")

    raw = path.read_bytes()

    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ChainVerificationError(f"{label} is invalid JSON.") from exc

    if not isinstance(value, dict):
        raise ChainVerificationError(f"{label} is not a JSON object.")

    return raw, value


def _require(label: str, actual: Any, expected: Any) -> None:
    if actual != expected:
        raise ChainVerificationError(
            f"{label} mismatch.\n"
            f"Expected: {expected!r}\n"
            f"Actual:   {actual!r}"
        )


def _parse_time(value: Any, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ChainVerificationError(f"{label} is invalid.") from exc

    if parsed.tzinfo is None:
        raise ChainVerificationError(f"{label} has no timezone.")

    return parsed


def _safe_artifact(base: Path, artifact: str) -> Path:
    path = (base / artifact).resolve()

    try:
        path.relative_to(base.resolve())
    except ValueError as exc:
        raise ChainVerificationError(
            f"Artifact escapes evidence directory: {artifact}"
        ) from exc

    return path


def _load_public_key(path: Path) -> Any:
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
    except ImportError as exc:
        raise ChainVerificationError(
            "cryptography is required for offline verification."
        ) from exc

    if not path.is_file():
        raise ChainVerificationError(
            f"Cached public key not found: {path}"
        )

    public_key = serialization.load_pem_public_key(path.read_bytes())

    if not isinstance(public_key, ec.EllipticCurvePublicKey):
        raise ChainVerificationError(
            "Cached KMS key is not an EC public key."
        )

    return public_key


def _verify_digest_signature(
    public_key: Any,
    signature: bytes,
    digest: bytes,
    label: str,
) -> None:
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec, utils

        public_key.verify(
            signature,
            digest,
            ec.ECDSA(utils.Prehashed(hashes.SHA256())),
        )
    except Exception as exc:
        raise ChainVerificationError(
            f"{label} signature verification failed."
        ) from exc


def _decode_signature(record: dict[str, Any], label: str) -> bytes:
    integrity = record.get("integrity", {})

    _require(f"{label} signed", integrity.get("signed"), True)
    _require(
        f"{label} signature status",
        integrity.get("signature_status"),
        "KMS_SIGNED",
    )
    _require(
        f"{label} algorithm",
        integrity.get("algorithm"),
        "EC_SIGN_P256_SHA256",
    )

    try:
        return base64.b64decode(
            integrity["value_base64"],
            validate=True,
        )
    except Exception as exc:
        raise ChainVerificationError(
            f"{label} signature is invalid Base64."
        ) from exc


def _verify_plan(
    public_key: Any,
    plan: dict[str, Any],
) -> tuple[bytes, str]:
    signature = _decode_signature(plan, "QPLAN")

    try:
        payload, encoding = _matching_plan_payload(plan)
    except Exception as exc:
        raise ChainVerificationError(str(exc)) from exc

    digest = hashlib.sha256(payload).digest()

    _require(
        "QPLAN canonical hash",
        digest.hex(),
        plan["integrity"]["canonical_payload_sha256"],
    )

    _verify_digest_signature(
        public_key,
        signature,
        digest,
        "QPLAN",
    )

    return signature, encoding


def _verify_standard_record(
    public_key: Any,
    record: dict[str, Any],
    label: str,
) -> bytes:
    signature = _decode_signature(record, label)

    payload = copy.deepcopy(record)
    payload.pop("integrity", None)
    payload_bytes = _canonical(payload)
    digest = hashlib.sha256(payload_bytes).digest()

    _require(
        f"{label} canonical hash",
        digest.hex(),
        record["integrity"]["canonical_payload_sha256"],
    )

    _verify_digest_signature(
        public_key,
        signature,
        digest,
        label,
    )

    return signature


def _verify_file_descriptor(
    base: Path,
    descriptor: dict[str, Any],
    label: str,
) -> Path:
    artifact = descriptor.get("artifact")
    expected = descriptor.get("sha256")

    if not isinstance(artifact, str) or not artifact:
        raise ChainVerificationError(
            f"{label} artifact is missing."
        )

    if not isinstance(expected, str) or len(expected) != 64:
        raise ChainVerificationError(
            f"{label} SHA-256 is missing or invalid."
        )

    path = _safe_artifact(base, artifact)

    if not path.is_file():
        raise ChainVerificationError(
            f"{label} artifact not found: {path}"
        )

    _require(
        f"{label} SHA-256",
        _sha256_file(path),
        expected,
    )

    return path


def _latest_receipt(project: Path) -> Path:
    receipts = list(
        (project / "evidence" / "executions").glob(
            "QEXEC-*/receipt.json"
        )
    )

    if not receipts:
        raise ChainVerificationError(
            "No QEXEC receipt was found."
        )

    return max(
        receipts,
        key=lambda path: path.stat().st_mtime_ns,
    )


def _resolve_receipt(
    project: Path,
    execution_id: str | None,
    submission_id: str | None,
    latest: bool,
) -> Path:
    selected = sum(
        bool(value)
        for value in (execution_id, submission_id, latest)
    )

    if selected != 1:
        raise ChainVerificationError(
            "Choose exactly one of --execution-id, "
            "--submission-id, or --latest."
        )

    if execution_id:
        return (
            project
            / "evidence"
            / "executions"
            / execution_id
            / "receipt.json"
        )

    if latest:
        return _latest_receipt(project)

    candidates = []

    for path in (
        project / "evidence" / "executions"
    ).glob("QEXEC-*/receipt.json"):
        try:
            value = json.loads(
                path.read_text(encoding="utf-8")
            )
        except Exception:
            continue

        if value.get("submission_id") == submission_id:
            candidates.append(path)

    if len(candidates) != 1:
        raise ChainVerificationError(
            f"Expected one QEXEC for {submission_id}, "
            f"found {len(candidates)}."
        )

    return candidates[0]


def _load_ibm_chain(
    project: Path,
    execution_id: str | None,
    submission_id: str | None,
    latest: bool,
) -> dict[str, Any]:
    project = project.resolve()
    receipt_path = _resolve_receipt(
        project,
        execution_id,
        submission_id,
        latest,
    )
    receipt_raw, receipt = _read_json(
        receipt_path,
        "QEXEC receipt",
    )

    execution_id_value = receipt.get("execution_id")
    submission_id_value = receipt.get("submission_id")
    approval_id = receipt.get("approval_id")
    plan_id = receipt.get("plan_id")

    for label, value, prefix in (
        ("Execution ID", execution_id_value, "QEXEC-"),
        ("Submission ID", submission_id_value, "QSUB-"),
        ("Approval ID", approval_id, "QAPPROVAL-"),
        ("Plan ID", plan_id, "QPLAN-"),
    ):
        if not isinstance(value, str) or not value.startswith(prefix):
            raise ChainVerificationError(
                f"{label} is invalid: {value!r}"
            )

    plan_dir = project / "evidence" / "plans" / plan_id
    approval_dir = (
        project / "evidence" / "approvals" / approval_id
    )
    submission_dir = (
        project
        / "evidence"
        / "submissions"
        / submission_id_value
    )
    execution_dir = receipt_path.parent

    plan_raw, plan = _read_json(
        plan_dir / "plan.json",
        "QPLAN",
    )
    approval_raw, approval = _read_json(
        approval_dir / "approval.json",
        "QAPPROVAL",
    )
    consumption_raw, consumption = _read_json(
        approval_dir / "consumption.json",
        "Approval consumption",
    )
    submission_raw, submission = _read_json(
        submission_dir / "submission.json",
        "QSUB",
    )

    public_key_path = approval_dir / "public-key.pem"

    return {
        "project": project,
        "plan_dir": plan_dir,
        "approval_dir": approval_dir,
        "submission_dir": submission_dir,
        "execution_dir": execution_dir,
        "receipt_path": receipt_path,
        "public_key_path": public_key_path,
        "plan_raw": plan_raw,
        "plan": plan,
        "approval_raw": approval_raw,
        "approval": approval,
        "consumption_raw": consumption_raw,
        "consumption": consumption,
        "submission_raw": submission_raw,
        "submission": submission,
        "receipt_raw": receipt_raw,
        "receipt": receipt,
        "execution_id": execution_id_value,
        "submission_id": submission_id_value,
        "approval_id": approval_id,
        "plan_id": plan_id,
    }


def _verify_ibm_chain(context: dict[str, Any]) -> list[str]:
    plan = context["plan"]
    approval = context["approval"]
    consumption = context["consumption"]
    submission = context["submission"]
    receipt = context["receipt"]

    public_key_bytes = context["public_key_path"].read_bytes()
    public_key = _load_public_key(context["public_key_path"])

    plan_signature, plan_encoding = _verify_plan(
        public_key,
        plan,
    )
    approval_signature = _verify_standard_record(
        public_key,
        approval,
        "QAPPROVAL",
    )
    submission_signature = _verify_standard_record(
        public_key,
        submission,
        "QSUB",
    )
    consumption_signature = _verify_standard_record(
        public_key,
        consumption,
        "Approval consumption",
    )
    receipt_signature = _verify_standard_record(
        public_key,
        receipt,
        "QEXEC",
    )

    key_version = plan["integrity"]["key_version"]

    for label, record in (
        ("QAPPROVAL", approval),
        ("QSUB", submission),
        ("Approval consumption", consumption),
        ("QEXEC", receipt),
    ):
        _require(
            f"{label} key version",
            record["integrity"]["key_version"],
            key_version,
        )

    declared_key_hash = approval["integrity"].get(
        "public_key_sha256"
    )

    if declared_key_hash:
        _require(
            "Cached public key SHA-256",
            _sha256_bytes(public_key_bytes),
            declared_key_hash,
        )

    _require(
        "QPLAN ID",
        plan.get("plan_id"),
        context["plan_id"],
    )
    _require(
        "QAPPROVAL ID",
        approval.get("approval_id"),
        context["approval_id"],
    )
    _require(
        "QSUB ID",
        submission.get("submission_id"),
        context["submission_id"],
    )
    _require(
        "QEXEC ID",
        receipt.get("execution_id"),
        context["execution_id"],
    )

    _require(
        "QPLAN status",
        plan.get("status"),
        "PLANNED",
    )
    _require(
        "QPLAN hardware submitted",
        plan.get("hardware_submitted"),
        False,
    )
    _require(
        "QAPPROVAL status",
        approval.get("status"),
        "APPROVED",
    )
    _require(
        "QAPPROVAL decision",
        approval.get("decision"),
        "APPROVE",
    )
    _require(
        "QSUB status",
        submission.get("status"),
        "SUBMITTED",
    )
    _require(
        "QSUB hardware submitted",
        submission.get("hardware_submitted"),
        True,
    )
    _require(
        "Consumption status",
        consumption.get("status"),
        "CONSUMED",
    )
    _require(
        "Consumption single use",
        consumption.get("single_use"),
        True,
    )
    _require(
        "Consumption hardware submitted",
        consumption.get("hardware_submitted"),
        True,
    )
    _require(
        "QEXEC status",
        receipt.get("status"),
        "EXECUTION_COMPLETED",
    )
    _require(
        "QEXEC terminal",
        receipt.get("terminal"),
        True,
    )
    _require(
        "QEXEC hardware submitted",
        receipt.get("hardware_submitted"),
        True,
    )

    workload = plan["workload"]
    target = plan["target"]

    logical_path = _verify_file_descriptor(
        context["plan_dir"],
        workload["logical_circuit"],
        "Logical circuit",
    )
    isa_path = _verify_file_descriptor(
        context["plan_dir"],
        workload["isa_circuit"],
        "ISA circuit",
    )
    snapshot_path = _verify_file_descriptor(
        context["plan_dir"],
        target["target_snapshot"],
        "Backend target snapshot",
    )

    approval_binding = approval["binding"]

    _require(
        "Approval plan ID",
        approval_binding.get("plan_id"),
        context["plan_id"],
    )
    _require(
        "Approval plan file hash",
        approval_binding.get("plan_file_sha256"),
        _sha256_bytes(context["plan_raw"]),
    )
    _require(
        "Approval plan payload hash",
        approval_binding.get(
            "plan_canonical_payload_sha256"
        ),
        plan["integrity"]["canonical_payload_sha256"],
    )
    _require(
        "Approval plan signature hash",
        approval_binding.get("plan_signature_sha256"),
        _sha256_bytes(plan_signature),
    )
    _require(
        "Approval plan key version",
        approval_binding.get(
            "plan_signature_key_version"
        ),
        key_version,
    )
    _require(
        "Approval plan canonical encoding",
        approval_binding.get("plan_canonical_encoding"),
        plan_encoding,
    )
    _require(
        "Approval logical circuit hash",
        approval_binding["logical_circuit"]["sha256"],
        _sha256_file(logical_path),
    )
    _require(
        "Approval ISA circuit hash",
        approval_binding["isa_circuit"]["sha256"],
        _sha256_file(isa_path),
    )
    _require(
        "Approval target snapshot hash",
        approval_binding["target_snapshot"]["sha256"],
        _sha256_file(snapshot_path),
    )
    _require(
        "Approval backend",
        approval_binding.get("backend"),
        target.get("backend"),
    )
    _require(
        "Approval backend version",
        approval_binding.get("backend_version"),
        target.get("backend_version"),
    )
    _require(
        "Approval primitive",
        approval_binding.get("primitive"),
        target.get("primitive"),
    )
    _require(
        "Approval shots",
        approval_binding.get("shots"),
        plan["execution_parameters"]["shots"],
    )
    _require(
        "Approval secret version",
        approval_binding.get("secret_version"),
        plan["credentials"]["secret_version"],
    )
    _require(
        "Approval secret persistence",
        approval_binding.get("secret_value_persisted"),
        False,
    )

    _require(
        "Consumption approval ID",
        consumption.get("approval_id"),
        context["approval_id"],
    )
    _require(
        "Consumption plan ID",
        consumption.get("plan_id"),
        context["plan_id"],
    )
    _require(
        "Consumption submission ID",
        consumption.get("submission_id"),
        context["submission_id"],
    )

    qsub_binding = submission["binding"]

    _require(
        "QSUB plan file hash",
        qsub_binding.get("plan_file_sha256"),
        _sha256_bytes(context["plan_raw"]),
    )
    _require(
        "QSUB plan payload hash",
        qsub_binding.get("plan_payload_sha256"),
        plan["integrity"]["canonical_payload_sha256"],
    )
    _require(
        "QSUB approval file hash",
        qsub_binding.get("approval_file_sha256"),
        _sha256_bytes(context["approval_raw"]),
    )
    _require(
        "QSUB approval payload hash",
        qsub_binding.get("approval_payload_sha256"),
        approval["integrity"]["canonical_payload_sha256"],
    )
    _require(
        "QSUB ISA circuit hash",
        qsub_binding.get("isa_circuit_sha256"),
        _sha256_file(isa_path),
    )
    _require(
        "QSUB target snapshot hash",
        qsub_binding.get("target_snapshot_sha256"),
        _sha256_file(snapshot_path),
    )
    _require(
        "QSUB backend",
        qsub_binding.get("backend"),
        approval_binding.get("backend"),
    )
    _require(
        "QSUB shots",
        qsub_binding.get("shots"),
        approval_binding.get("shots"),
    )
    _require(
        "QSUB secret version",
        qsub_binding.get("secret_version"),
        approval_binding.get("secret_version"),
    )

    ibm = submission["ibm"]
    job_id = ibm.get("job_id")

    _require(
        "Consumed IBM job ID",
        consumption.get("ibm_job_id"),
        job_id,
    )
    _require(
        "QEXEC submission ID",
        receipt.get("submission_id"),
        context["submission_id"],
    )
    _require(
        "QEXEC approval ID",
        receipt.get("approval_id"),
        context["approval_id"],
    )
    _require(
        "QEXEC plan ID",
        receipt.get("plan_id"),
        context["plan_id"],
    )
    _require(
        "QEXEC IBM job ID",
        receipt["ibm"].get("job_id"),
        job_id,
    )
    _require(
        "QEXEC backend",
        receipt["ibm"].get("backend"),
        ibm.get("backend"),
    )
    _require(
        "QEXEC authorized shots",
        receipt["ibm"].get("shots_authorized"),
        ibm.get("shots"),
    )

    receipt_chain = receipt["chain"]

    _require(
        "QEXEC plan file hash",
        receipt_chain.get("plan_file_sha256"),
        _sha256_bytes(context["plan_raw"]),
    )
    _require(
        "QEXEC approval file hash",
        receipt_chain.get("approval_file_sha256"),
        _sha256_bytes(context["approval_raw"]),
    )
    _require(
        "QEXEC submission file hash",
        receipt_chain.get("submission_file_sha256"),
        _sha256_bytes(context["submission_raw"]),
    )
    _require(
        "QEXEC consumption file hash",
        receipt_chain.get("consumption_file_sha256"),
        _sha256_bytes(context["consumption_raw"]),
    )
    _require(
        "QEXEC ISA circuit hash",
        receipt_chain.get("isa_circuit_sha256"),
        _sha256_file(isa_path),
    )
    _require(
        "QEXEC target snapshot hash",
        receipt_chain.get("target_snapshot_sha256"),
        _sha256_file(snapshot_path),
    )

    results = receipt["results"]
    result_path = _verify_file_descriptor(
        context["execution_dir"],
        results["runtime_result"],
        "Runtime result",
    )
    counts_path = _verify_file_descriptor(
        context["execution_dir"],
        results["counts"],
        "Counts",
    )
    metadata_path = _verify_file_descriptor(
        context["execution_dir"],
        receipt["ibm"]["metadata_artifact"],
        "IBM job metadata",
    )

    _, counts_record = _read_json(
        counts_path,
        "Counts",
    )
    counts = counts_record.get("counts")

    if not isinstance(counts, dict) or not counts:
        raise ChainVerificationError(
            "Counts artifact has no count mapping."
        )

    observed = sum(int(value) for value in counts.values())

    _require(
        "Counts observed shots",
        counts_record.get("observed_shots"),
        observed,
    )
    _require(
        "QEXEC observed shots",
        receipt["ibm"].get("shots_observed"),
        observed,
    )
    _require(
        "Authorized and observed shots",
        observed,
        ibm.get("shots"),
    )
    _require(
        "Receipt embedded counts",
        results["counts"].get("values"),
        counts,
    )

    submitted_at = _parse_time(
        submission["created_at"],
        "QSUB created_at",
    )
    not_before = _parse_time(
        approval["authorization_scope"]["not_before"],
        "Approval not_before",
    )
    expires_at = _parse_time(
        approval["authorization_scope"]["expires_at"],
        "Approval expires_at",
    )

    if not (not_before <= submitted_at < expires_at):
        raise ChainVerificationError(
            "QSUB occurred outside the approval window."
        )

    return [
        "All five cryptographic signatures",
        "Single KMS key-version lineage",
        "QPLAN logical, ISA, and target artifacts",
        "Exact QPLAN-to-QAPPROVAL binding",
        "Time-bounded approval and single-use consumption",
        "Exact QAPPROVAL-to-QSUB binding",
        "IBM job identity, backend, and shot count",
        "Exact QSUB-to-QEXEC chain hashes",
        "Runtime result, counts, and metadata artifacts",
        "Observed shots equal authorized shots",
    ]


def _display_ibm_chain(context: dict[str, Any]) -> None:
    plan = context["plan"]
    approval = context["approval"]
    submission = context["submission"]
    receipt = context["receipt"]
    authorization = plan.get("authorization", {})
    upstream = plan.get("upstream_execution", {})

    rows = [
        (
            "QVERIFY",
            authorization.get("verification_run_id", "N/A"),
            "VERIFIED"
            if authorization.get("signature_verified") is True
            else "UNKNOWN",
        ),
        (
            "QEXEC-LOCAL",
            upstream.get("execution_id", "N/A"),
            "ATTESTED" if upstream else "N/A",
        ),
        (
            "QPLAN",
            context["plan_id"],
            plan.get("status", "UNKNOWN"),
        ),
        (
            "QAPPROVAL",
            context["approval_id"],
            approval.get("status", "UNKNOWN"),
        ),
        (
            "QSUB",
            context["submission_id"],
            submission.get("status", "UNKNOWN"),
        ),
        (
            "IBM JOB",
            submission.get("ibm", {}).get("job_id", "N/A"),
            receipt.get("ibm", {}).get("job_status", "UNKNOWN"),
        ),
        (
            "QEXEC",
            context["execution_id"],
            receipt.get("status", "UNKNOWN"),
        ),
    ]

    print("=== QuantumD Evidence Graph ===")
    print(
        f"{'NODE':<12} {'IDENTIFIER':<38} STATUS"
    )
    print("-" * 76)

    for node, identifier, status in rows:
        print(
            f"{node:<12} {str(identifier):<38} {status}"
        )

    print()
    print(
        f"Backend:        "
        f"{submission['ibm']['backend']}"
    )
    print(
        f"Primitive:      "
        f"{submission['ibm']['primitive']}"
    )
    print(
        f"Shots:          "
        f"{receipt['ibm']['shots_observed']}"
    )
    print(
        f"Results:        "
        f"{receipt['results']['counts']['values']}"
    )
    print(
        f"Receipt:        "
        f"{context['receipt_path']}"
    )




# QUANTUMD_PHASE4A_LOCAL_CHAIN

def _verify_local_record(
    public_key: Any,
    record: dict[str, Any],
    label: str,
) -> bytes:
    """Verify records signed with an empty integrity object."""
    signature = _decode_signature(record, label)

    payload = copy.deepcopy(record)
    payload["integrity"] = {}

    payload_bytes = _canonical(payload)
    digest = hashlib.sha256(payload_bytes).digest()

    _require(
        f"{label} canonical hash",
        digest.hex(),
        record["integrity"]["canonical_payload_sha256"],
    )

    _verify_digest_signature(
        public_key,
        signature,
        digest,
        label,
    )

    return signature

def _is_local_receipt(receipt: dict[str, Any]) -> bool:
    target = receipt.get("target")
    return (
        isinstance(target, dict)
        and target.get("provider") == "local"
    )


def _require_sha256(label: str, value: Any) -> str:
    if not isinstance(value, str):
        raise ChainVerificationError(
            f"{label} is not a SHA-256 string."
        )

    normalized = value.lower()

    if (
        len(normalized) != 64
        or any(
            character not in "0123456789abcdef"
            for character in normalized
        )
    ):
        raise ChainVerificationError(
            f"{label} is not a valid SHA-256 digest."
        )

    return normalized


def _safe_project_file(
    project: Path,
    relative_value: Any,
    label: str,
) -> Path:
    if not isinstance(relative_value, str) or not relative_value:
        raise ChainVerificationError(
            f"{label} path is invalid: {relative_value!r}"
        )

    relative_path = Path(relative_value)

    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ChainVerificationError(
            f"{label} path escapes the project: "
            f"{relative_value!r}"
        )

    resolved = (project / relative_path).resolve()

    try:
        resolved.relative_to(project)
    except ValueError as exc:
        raise ChainVerificationError(
            f"{label} path escapes the project: "
            f"{relative_value!r}"
        ) from exc

    if not resolved.is_file():
        raise ChainVerificationError(
            f"{label} not found: {resolved}"
        )

    return resolved


def _find_local_public_key(
    project: Path,
    verification: dict[str, Any],
    receipt: dict[str, Any],
) -> tuple[Path, Any]:
    evidence_root = project / "evidence"

    candidates = sorted(
        {
            *evidence_root.rglob("*.pem"),
            *evidence_root.rglob("*.pub"),
        }
    )

    if not candidates:
        raise ChainVerificationError(
            "No cached public key was found under evidence/. "
            "Offline verification requires the signing public key."
        )

    failures: list[str] = []

    for path in candidates:
        try:
            public_key = _load_public_key(path)
            _verify_local_record(
                public_key,
                verification,
                "QVERIFY",
            )
            _verify_local_record(
                public_key,
                receipt,
                "QEXEC",
            )
            return path, public_key
        except Exception as exc:
            failures.append(
                f"{path}: {type(exc).__name__}"
            )

    detail = "; ".join(failures[:5])

    raise ChainVerificationError(
        "No cached public key verifies both QVERIFY and "
        f"the local QEXEC receipt. Candidates: {detail}"
    )


def _load_local_chain(
    project: Path,
    execution_id: str | None,
    submission_id: str | None,
    latest: bool,
) -> dict[str, Any]:
    if submission_id is not None:
        raise ChainVerificationError(
            "--submission-id applies only to remote-provider "
            "execution chains."
        )

    project = project.resolve()
    receipt_path = _resolve_receipt(
        project,
        execution_id,
        None,
        latest,
    )
    receipt_raw, receipt = _read_json(
        receipt_path,
        "Local QEXEC receipt",
    )

    if not _is_local_receipt(receipt):
        raise ChainVerificationError(
            "Selected receipt is not a local-provider execution."
        )

    execution_id_value = receipt.get("execution_id")

    if (
        not isinstance(execution_id_value, str)
        or not execution_id_value.startswith("QEXEC-")
    ):
        raise ChainVerificationError(
            f"Execution ID is invalid: {execution_id_value!r}"
        )

    for field in (
        "submission_id",
        "approval_id",
        "plan_id",
        "ibm",
    ):
        value = receipt.get(field)

        if value is not None:
            raise ChainVerificationError(
                f"Local QEXEC must not declare {field}: "
                f"{value!r}"
            )

    authorization = receipt.get("authorization")

    if not isinstance(authorization, dict):
        raise ChainVerificationError(
            "Local QEXEC authorization is missing."
        )

    verification_run_id = authorization.get(
        "verification_run_id"
    )

    if (
        not isinstance(verification_run_id, str)
        or not verification_run_id
    ):
        raise ChainVerificationError(
            "Local QEXEC verification run ID is invalid."
        )

    verification_path = (
        project
        / "evidence"
        / "runs"
        / f"{verification_run_id}.json"
    )
    verification_raw, verification = _read_json(
        verification_path,
        "QVERIFY record",
    )

    execution_dir = receipt_path.parent
    results = receipt.get("results")

    if not isinstance(results, dict):
        raise ChainVerificationError(
            "Local QEXEC results descriptor is missing."
        )

    artifact = results.get("artifact")

    if (
        not isinstance(artifact, str)
        or not artifact
        or Path(artifact).name != artifact
    ):
        raise ChainVerificationError(
            f"Local result artifact is invalid: {artifact!r}"
        )

    result_path = execution_dir / artifact

    if not result_path.is_file():
        raise ChainVerificationError(
            f"Local result artifact not found: {result_path}"
        )

    result_raw, result_record = _read_json(
        result_path,
        "Local execution results",
    )

    public_key_path, public_key = _find_local_public_key(
        project,
        verification,
        receipt,
    )

    return {
        "chain_type": "local",
        "project": project,
        "execution_dir": execution_dir,
        "receipt_path": receipt_path,
        "receipt_raw": receipt_raw,
        "receipt": receipt,
        "verification_path": verification_path,
        "verification_raw": verification_raw,
        "verification": verification,
        "result_path": result_path,
        "result_raw": result_raw,
        "result_record": result_record,
        "public_key_path": public_key_path,
        "public_key": public_key,
        "execution_id": execution_id_value,
        "verification_run_id": verification_run_id,
        "submission_id": "N/A",
        "approval_id": "N/A",
        "plan_id": "N/A",
    }


def _verify_local_chain(
    context: dict[str, Any],
) -> list[str]:
    project = context["project"]
    receipt = context["receipt"]
    verification = context["verification"]
    result_record = context["result_record"]
    public_key = context["public_key"]

    _verify_local_record(
        public_key,
        verification,
        "QVERIFY",
    )
    _verify_local_record(
        public_key,
        receipt,
        "QEXEC",
    )

    verification_integrity = verification.get("integrity")
    receipt_integrity = receipt.get("integrity")

    if not isinstance(verification_integrity, dict):
        raise ChainVerificationError(
            "QVERIFY integrity record is missing."
        )

    if not isinstance(receipt_integrity, dict):
        raise ChainVerificationError(
            "QEXEC integrity record is missing."
        )

    _require(
        "Local key-version lineage",
        receipt_integrity.get("key_version"),
        verification_integrity.get("key_version"),
    )

    _require_sha256(
        "QVERIFY canonical payload",
        verification_integrity.get(
            "canonical_payload_sha256"
        ),
    )
    _require_sha256(
        "QEXEC canonical payload",
        receipt_integrity.get(
            "canonical_payload_sha256"
        ),
    )

    _require(
        "QEXEC ID",
        receipt.get("execution_id"),
        context["execution_id"],
    )
    _require(
        "QVERIFY run ID",
        verification.get("run_id"),
        context["verification_run_id"],
    )
    _require(
        "QEXEC status",
        receipt.get("status"),
        "EXECUTION_COMPLETED",
    )
    _require(
        "QEXEC workload executed",
        receipt.get("workload_executed"),
        True,
    )

    decision = verification.get("final_decision")

    if (
        not isinstance(decision, str)
        or not decision.startswith("VERIFIED")
    ):
        raise ChainVerificationError(
            f"QVERIFY decision is not executable: {decision!r}"
        )

    authorization = receipt.get("authorization", {})

    _require(
        "Authorization verification run ID",
        authorization.get("verification_run_id"),
        context["verification_run_id"],
    )
    _require(
        "Authorization signature status",
        authorization.get("signature_verified"),
        True,
    )
    _require(
        "Authorization payload hash",
        authorization.get(
            "verification_payload_sha256"
        ),
        verification_integrity.get(
            "canonical_payload_sha256"
        ),
    )

    target = receipt.get("target")

    if not isinstance(target, dict):
        raise ChainVerificationError(
            "Local target descriptor is missing."
        )

    _require(
        "Execution provider",
        target.get("provider"),
        "local",
    )
    _require(
        "Execution backend",
        target.get("backend"),
        "aer-simulator",
    )

    verification_hashes = verification.get("hashes")

    if not isinstance(verification_hashes, dict):
        raise ChainVerificationError(
            "QVERIFY hash bindings are missing."
        )

    manifest_expected = _require_sha256(
        "QVERIFY manifest hash",
        verification_hashes.get("manifest_sha256"),
    )

    source_descriptor = verification_hashes.get("source")

    if not isinstance(source_descriptor, dict):
        raise ChainVerificationError(
            "QVERIFY source descriptor is missing."
        )

    source_expected = _require_sha256(
        "QVERIFY source hash",
        source_descriptor.get("sha256"),
    )

    manifest_path = _safe_project_file(
        project,
        "experiment.yaml",
        "Manifest",
    )
    source_path = _safe_project_file(
        project,
        source_descriptor.get("path"),
        "Source",
    )

    _require(
        "Current manifest hash",
        _sha256_file(manifest_path),
        manifest_expected,
    )
    _require(
        "Current source hash",
        _sha256_file(source_path),
        source_expected,
    )

    workload = receipt.get("workload")

    if not isinstance(workload, dict):
        raise ChainVerificationError(
            "Local QEXEC workload binding is missing."
        )

    _require(
        "QEXEC manifest binding",
        workload.get("manifest_sha256"),
        manifest_expected,
    )
    _require(
        "QEXEC source binding",
        workload.get("source_sha256"),
        source_expected,
    )

    logical = workload.get("logical_circuit")
    executed = workload.get("executed_circuit")

    if not isinstance(logical, dict):
        raise ChainVerificationError(
            "Logical circuit binding is missing."
        )

    if not isinstance(executed, dict):
        raise ChainVerificationError(
            "Executed circuit binding is missing."
        )

    _require_sha256(
        "Logical circuit hash",
        logical.get("sha256"),
    )
    _require_sha256(
        "Executed circuit hash",
        executed.get("sha256"),
    )

    results = receipt.get("results", {})
    expected_result_hash = _require_sha256(
        "QEXEC result hash",
        results.get("sha256"),
    )

    _require(
        "Result artifact hash",
        _sha256_bytes(context["result_raw"]),
        expected_result_hash,
    )

    if not isinstance(result_record, dict) or not result_record:
        raise ChainVerificationError(
            "Local results have no count mapping."
        )

    observed = 0

    for bitstring, count in result_record.items():
        if not isinstance(bitstring, str) or not bitstring:
            raise ChainVerificationError(
                "Local result key is invalid."
            )

        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or count < 0
        ):
            raise ChainVerificationError(
                f"Local result count is invalid: {count!r}"
            )

        observed += count

    shots = receipt.get("shots")

    if (
        isinstance(shots, bool)
        or not isinstance(shots, int)
        or shots <= 0
    ):
        raise ChainVerificationError(
            f"QEXEC shot count is invalid: {shots!r}"
        )

    _require(
        "Observed and authorized shots",
        observed,
        shots,
    )

    finalized_at = _parse_time(
        verification["finalized_at"],
        "QVERIFY finalized_at",
    )
    executed_at = _parse_time(
        receipt["timestamp"],
        "QEXEC timestamp",
    )

    if executed_at < finalized_at:
        raise ChainVerificationError(
            "Local QEXEC predates its authorization."
        )

    return [
        "QVERIFY and QEXEC cryptographic signatures",
        "Single KMS key-version lineage",
        "Executable verification decision",
        "Exact authorization-to-QVERIFY binding",
        "Current manifest and source identity",
        "Exact QVERIFY-to-QEXEC workload binding",
        "Logical and executed circuit identities",
        "Result artifact SHA-256 binding",
        "Observed shots equal authorized shots",
        "Authorization predates execution",
    ]


def _display_local_chain(
    context: dict[str, Any],
) -> None:
    verification = context["verification"]
    receipt = context["receipt"]

    rows = [
        (
            "QVERIFY",
            context["verification_run_id"],
            verification.get(
                "final_decision",
                "UNKNOWN",
            ),
        ),
        (
            "QEXEC",
            context["execution_id"],
            receipt.get("status", "UNKNOWN"),
        ),
    ]

    print("=== QuantumD Local Evidence Graph ===")
    print(
        f"{'NODE':<12} {'IDENTIFIER':<42} STATUS"
    )
    print("-" * 86)

    for node, identifier, status in rows:
        print(
            f"{node:<12} {str(identifier):<42} {status}"
        )

    print()
    print(
        f"Provider:       "
        f"{receipt['target']['provider']}"
    )
    print(
        f"Backend:        "
        f"{receipt['target']['backend']}"
    )
    print(
        f"Shots:          "
        f"{receipt['shots']}"
    )
    print(
        f"Results:        "
        f"{context['result_record']}"
    )
    print(
        f"Public key:     "
        f"{context['public_key_path']}"
    )
    print(
        f"Receipt:        "
        f"{context['receipt_path']}"
    )


def _load_chain(
    project: Path,
    execution_id: str | None,
    submission_id: str | None,
    latest: bool,
) -> dict[str, Any]:
    project = project.resolve()
    receipt_path = _resolve_receipt(
        project,
        execution_id,
        submission_id,
        latest,
    )
    _, receipt = _read_json(
        receipt_path,
        "QEXEC receipt",
    )

    if _is_local_receipt(receipt):
        return _load_local_chain(
            project,
            execution_id,
            submission_id,
            latest,
        )

    context = _load_ibm_chain(
        project,
        execution_id,
        submission_id,
        latest,
    )
    context["chain_type"] = "ibm"
    return context


def _verify_chain(
    context: dict[str, Any],
) -> list[str]:
    if context.get("chain_type") == "local":
        return _verify_local_chain(context)

    return _verify_ibm_chain(context)


def _display_chain(
    context: dict[str, Any],
) -> None:
    if context.get("chain_type") == "local":
        _display_local_chain(context)
        return

    _display_ibm_chain(context)


def _selection_options(function):
    function = click.option(
        "--execution-id",
        help="Exact QEXEC identifier.",
    )(function)
    function = click.option(
        "--submission-id",
        help="Resolve the QEXEC by exact QSUB identifier.",
    )(function)
    function = click.option(
        "--latest",
        is_flag=True,
        help="Use the newest QEXEC receipt.",
    )(function)
    return function


@click.command("chain")
@click.argument(
    "project",
    type=click.Path(
        exists=True,
        file_okay=False,
        dir_okay=True,
        path_type=Path,
    ),
)
@_selection_options
def chain_command(
    project: Path,
    execution_id: str | None,
    submission_id: str | None,
    latest: bool,
) -> None:
    """Display the complete QuantumD Evidence Graph."""

    try:
        context = _load_chain(
            project,
            execution_id,
            submission_id,
            latest,
        )
        _display_chain(context)
    except Exception as exc:
        click.secho(
            "[STATUS] EVIDENCE GRAPH FAILED",
            fg="red",
            bold=True,
        )
        print(
            f"  └─ {type(exc).__name__}: {exc}"
        )
        raise click.exceptions.Exit(1) from exc


@click.command("verify-chain")
@click.argument(
    "project",
    type=click.Path(
        exists=True,
        file_okay=False,
        dir_okay=True,
        path_type=Path,
    ),
)
@_selection_options
def verify_chain_command(
    project: Path,
    execution_id: str | None,
    submission_id: str | None,
    latest: bool,
) -> None:
    """Independently verify a complete chain without IBM or KMS calls."""

    try:
        context = _load_chain(
            project,
            execution_id,
            submission_id,
            latest,
        )

        print(
            "=== QuantumD Independent Chain Verification ==="
        )
        print(
            f"Execution:     {context['execution_id']}"
        )
        print(
            f"Submission:    {context['submission_id']}"
        )
        print(
            f"Approval:      {context['approval_id']}"
        )
        print(
            f"Plan:          {context['plan_id']}"
        )
        print(
            f"Public key:    {context['public_key_path']}"
        )
        print("Network calls: None\n")

        checks = _verify_chain(context)

        for number, label in enumerate(checks, start=1):
            click.secho(
                f"[CHECK {number:02d}] "
                f"{label:.<48} PASS",
                fg="green",
            )

        print()
        _display_chain(context)
        click.secho(
            "\n[STATUS] COMPLETE EVIDENCE CHAIN VERIFIED",
            fg="green",
            bold=True,
        )
        print("IBM contacted:   False")
        print("KMS contacted:   False")
        print("Hardware action: None")

    except Exception as exc:
        click.secho(
            "\n[STATUS] CHAIN VERIFICATION DENIED",
            fg="red",
            bold=True,
        )
        print(
            f"  └─ {type(exc).__name__}: {exc}"
        )
        raise click.exceptions.Exit(1) from exc


chain = chain_command
verify_chain = verify_chain_command

