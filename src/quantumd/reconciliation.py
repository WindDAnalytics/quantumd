"""Reconcile a governed IBM Runtime job into a signed QEXEC receipt."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click

from quantumd.approval import (
    ApprovalError,
    _get_verified_public_key,
    _load_kms_client,
    _sha256_bytes,
    _sha256_file,
    _verify_artifact,
    _verify_ecdsa_signature,
    _verify_plan_signature,
)
from quantumd.submission import attest, backend_name, secret


class ReconciliationError(RuntimeError):
    """Raised when QEXEC reconciliation must fail closed."""


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
        raise ReconciliationError(f"{label} not found: {path}")
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReconciliationError(f"{label} is invalid JSON.") from exc
    if not isinstance(value, dict):
        raise ReconciliationError(f"{label} is not a JSON object.")
    return raw, value


def _require(label: str, actual: Any, expected: Any) -> None:
    if actual != expected:
        raise ReconciliationError(
            f"{label} mismatch.\nExpected: {expected!r}\nActual:   {actual!r}"
        )


def _parse_time(value: Any, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReconciliationError(f"{label} is invalid.") from exc
    if parsed.tzinfo is None:
        raise ReconciliationError(f"{label} has no timezone.")
    return parsed.astimezone(timezone.utc)


def _verify_signed_json(
    client: Any,
    record: dict[str, Any],
    label: str,
) -> tuple[bytes, bytes]:
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

    payload = copy.deepcopy(record)
    payload.pop("integrity", None)
    payload_bytes = _canonical(payload)
    digest = hashlib.sha256(payload_bytes).digest()

    _require(
        f"{label} canonical payload hash",
        digest.hex(),
        integrity.get("canonical_payload_sha256"),
    )

    try:
        signature = base64.b64decode(
            integrity["value_base64"],
            validate=True,
        )
    except Exception as exc:
        raise ReconciliationError(
            f"{label} signature is invalid Base64."
        ) from exc

    public_key, _ = _get_verified_public_key(
        client,
        integrity["key_version"],
    )

    try:
        _verify_ecdsa_signature(
            public_key,
            signature,
            digest,
        )
    except Exception as exc:
        raise ReconciliationError(
            f"{label} signature verification failed."
        ) from exc

    declared_key_hash = integrity.get("public_key_sha256")
    if declared_key_hash:
        _require(
            f"{label} public key hash",
            _sha256_bytes(public_key),
            declared_key_hash,
        )

    return signature, public_key


def _runtime_value(value: Any) -> Any:
    return value() if callable(value) else value


def _job_backend_name(job: Any) -> str:
    backend = job.backend()
    if backend is None:
        raise ReconciliationError("IBM job has no backend.")
    return backend_name(backend)


def _find_existing_receipt(
    project: Path,
    submission_id: str,
    job_id: str,
) -> Path | None:
    root = project / "evidence" / "executions"
    if not root.exists():
        return None

    for path in root.glob("QEXEC-*/receipt.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if (
            value.get("submission_id") == submission_id
            and value.get("ibm", {}).get("job_id") == job_id
        ):
            return path
    return None


def _load_chain(
    project: Path,
    submission_id: str,
) -> dict[str, Any]:
    project = project.resolve()
    submission_dir = (
        project / "evidence" / "submissions" / submission_id
    )
    submission_path = submission_dir / "submission.json"
    submission_raw, submission = _read_json(
        submission_path,
        "QSUB",
    )

    _require(
        "QSUB ID",
        submission.get("submission_id"),
        submission_id,
    )
    _require(
        "QSUB schema",
        submission.get("schema_version"),
        "quantumd.ai/submission/v0.1",
    )
    _require(
        "QSUB status",
        submission.get("status"),
        "SUBMITTED",
    )
    _require(
        "QSUB hardware submission",
        submission.get("hardware_submitted"),
        True,
    )

    plan_id = submission.get("plan_id")
    approval_id = submission.get("approval_id")
    if not isinstance(plan_id, str) or not plan_id.startswith("QPLAN-"):
        raise ReconciliationError("QSUB contains an invalid plan ID.")
    if (
        not isinstance(approval_id, str)
        or not approval_id.startswith("QAPPROVAL-")
    ):
        raise ReconciliationError("QSUB contains an invalid approval ID.")

    plan_dir = project / "evidence" / "plans" / plan_id
    plan_path = plan_dir / "plan.json"
    plan_raw, plan = _read_json(plan_path, "QPLAN")

    approval_dir = (
        project / "evidence" / "approvals" / approval_id
    )
    approval_path = approval_dir / "approval.json"
    approval_raw, approval = _read_json(
        approval_path,
        "QAPPROVAL",
    )
    consumption_path = approval_dir / "consumption.json"
    consumption_raw, consumption = _read_json(
        consumption_path,
        "Approval consumption",
    )

    client = _load_kms_client()

    try:
        plan_key, plan_encoding, plan_signature = (
            _verify_plan_signature(client, plan)
        )
        logical = _verify_artifact(
            plan_dir,
            plan["workload"]["logical_circuit"],
            "Logical circuit",
        )
        isa = _verify_artifact(
            plan_dir,
            plan["workload"]["isa_circuit"],
            "ISA circuit",
        )
        target_snapshot = _verify_artifact(
            plan_dir,
            plan["target"]["target_snapshot"],
            "Backend target snapshot",
        )
    except ApprovalError as exc:
        raise ReconciliationError(str(exc)) from exc

    approval_signature, approval_key = _verify_signed_json(
        client,
        approval,
        "QAPPROVAL",
    )
    submission_signature, submission_key = _verify_signed_json(
        client,
        submission,
        "QSUB",
    )
    consumption_signature, _ = _verify_signed_json(
        client,
        consumption,
        "Approval consumption",
    )

    _require("QPLAN ID", plan.get("plan_id"), plan_id)
    _require(
        "QAPPROVAL ID",
        approval.get("approval_id"),
        approval_id,
    )
    _require(
        "Approval binding plan",
        approval.get("binding", {}).get("plan_id"),
        plan_id,
    )
    _require(
        "Consumption approval",
        consumption.get("approval_id"),
        approval_id,
    )
    _require(
        "Consumption plan",
        consumption.get("plan_id"),
        plan_id,
    )
    _require(
        "Consumption submission",
        consumption.get("submission_id"),
        submission_id,
    )
    _require(
        "Consumption status",
        consumption.get("status"),
        "CONSUMED",
    )
    _require(
        "Consumption hardware submission",
        consumption.get("hardware_submitted"),
        True,
    )

    job_id = submission.get("ibm", {}).get("job_id")
    if not isinstance(job_id, str) or not job_id:
        raise ReconciliationError("QSUB has no IBM job ID.")

    _require(
        "Consumption IBM job",
        consumption.get("ibm_job_id"),
        job_id,
    )

    binding = submission.get("binding", {})
    _require(
        "QSUB plan file hash",
        binding.get("plan_file_sha256"),
        _sha256_bytes(plan_raw),
    )
    _require(
        "QSUB plan payload hash",
        binding.get("plan_payload_sha256"),
        plan["integrity"]["canonical_payload_sha256"],
    )
    _require(
        "QSUB approval file hash",
        binding.get("approval_file_sha256"),
        _sha256_bytes(approval_raw),
    )
    _require(
        "QSUB approval payload hash",
        binding.get("approval_payload_sha256"),
        approval["integrity"]["canonical_payload_sha256"],
    )
    _require(
        "QSUB ISA circuit hash",
        binding.get("isa_circuit_sha256"),
        isa["sha256"],
    )
    _require(
        "QSUB target snapshot hash",
        binding.get("target_snapshot_sha256"),
        target_snapshot["sha256"],
    )
    _require(
        "QSUB backend",
        submission["ibm"].get("backend"),
        binding.get("backend"),
    )
    _require(
        "QSUB shots",
        submission["ibm"].get("shots"),
        binding.get("shots"),
    )

    submitted_at = _parse_time(
        submission.get("created_at"),
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
        raise ReconciliationError(
            "QSUB timestamp falls outside the approval window."
        )

    existing = _find_existing_receipt(
        project,
        submission_id,
        job_id,
    )

    return {
        "project": project,
        "submission_id": submission_id,
        "submission_dir": submission_dir,
        "submission_path": submission_path,
        "submission_raw": submission_raw,
        "submission": submission,
        "submission_signature": submission_signature,
        "submission_key": submission_key,
        "plan_id": plan_id,
        "plan_path": plan_path,
        "plan_raw": plan_raw,
        "plan": plan,
        "plan_signature": plan_signature,
        "plan_key": plan_key,
        "plan_encoding": plan_encoding,
        "approval_id": approval_id,
        "approval_path": approval_path,
        "approval_raw": approval_raw,
        "approval": approval,
        "approval_signature": approval_signature,
        "approval_key": approval_key,
        "consumption_path": consumption_path,
        "consumption_raw": consumption_raw,
        "consumption": consumption,
        "consumption_signature": consumption_signature,
        "logical": logical,
        "isa": isa,
        "target_snapshot": target_snapshot,
        "job_id": job_id,
        "binding": binding,
        "client": client,
        "existing": existing,
    }


def _service(context: dict[str, Any]) -> Any:
    try:
        from qiskit_ibm_runtime import QiskitRuntimeService
    except ImportError as exc:
        raise ReconciliationError(
            "qiskit-ibm-runtime is unavailable."
        ) from exc

    secret_version = context["binding"].get("secret_version")
    if not isinstance(secret_version, str) or not secret_version:
        raise ReconciliationError(
            "QSUB has no bound credential version."
        )

    token = secret(secret_version)
    try:
        return QiskitRuntimeService(
            channel="ibm_quantum_platform",
            token=token,
            instance=context["binding"].get("instance"),
        )
    finally:
        token = None


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temp.open("wb") as handle:
        handle.write(data)
        handle.flush()
        import os
        os.fsync(handle.fileno())
    import os
    os.chmod(temp, 0o444)
    os.replace(temp, path)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    data = (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )
        + "\n"
    ).encode("utf-8")
    _write_bytes(path, data)


def _counts_from_result(result: Any) -> dict[str, int]:
    try:
        if len(result) != 1:
            raise ReconciliationError(
                f"Expected one Sampler PUB result, received {len(result)}."
            )
        pub = result[0]
        joined = pub.join_data()
        counts = joined.get_counts()
    except ReconciliationError:
        raise
    except Exception as exc:
        raise ReconciliationError(
            "Unable to extract register-aware Sampler counts."
        ) from exc

    normalized = {
        str(key): int(value)
        for key, value in dict(counts).items()
    }
    if not normalized:
        raise ReconciliationError("IBM result contains no counts.")
    return dict(sorted(normalized.items()))


def _job_metadata(job: Any) -> dict[str, Any]:
    metadata: dict[str, Any] = {}

    for name in (
        "creation_date",
        "instance",
        "primitive_id",
        "session_id",
        "tags",
        "usage_estimation",
    ):
        try:
            value = _runtime_value(getattr(job, name))
        except Exception:
            continue
        if value is not None:
            metadata[name] = value

    try:
        metadata["metrics"] = job.metrics()
    except Exception as exc:
        metadata["metrics_unavailable"] = type(exc).__name__

    try:
        metadata["usage_seconds"] = job.usage()
    except Exception as exc:
        metadata["usage_unavailable"] = type(exc).__name__

    return metadata


def _terminal_failure_receipt(
    context: dict[str, Any],
    status: str,
    error_message: str | None,
    job_metadata: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    created = datetime.now(timezone.utc)
    execution_id = (
        f"QEXEC-{created:%Y%m%d}-{uuid.uuid4().hex[:8]}"
    )
    payload = {
        "schema_version": "quantumd.ai/execution/v0.1",
        "execution_id": execution_id,
        "created_at": created.isoformat(),
        "status": (
            "EXECUTION_CANCELLED"
            if status == "CANCELLED"
            else "EXECUTION_FAILED"
        ),
        "submission_id": context["submission_id"],
        "plan_id": context["plan_id"],
        "approval_id": context["approval_id"],
        "ibm": {
            "job_id": context["job_id"],
            "job_status": status,
            "backend": context["binding"]["backend"],
            "primitive": context["binding"]["primitive"],
            "shots_authorized": context["binding"]["shots"],
            "error_message": error_message,
            "metadata": job_metadata,
        },
        "results": None,
        "hardware_submitted": True,
        "terminal": True,
    }
    return execution_id, attest(payload, context)


@click.command("qexec")
@click.argument(
    "project",
    type=click.Path(
        exists=True,
        file_okay=False,
        dir_okay=True,
        path_type=Path,
    ),
)
@click.option(
    "--submission-id",
    required=True,
    help="Exact QSUB identifier to reconcile.",
)
@click.option(
    "--wait",
    "wait_for_result",
    is_flag=True,
    help="Block until IBM reaches a terminal state.",
)
@click.option(
    "--timeout",
    type=click.IntRange(min=1, max=86400),
    default=3600,
    show_default=True,
    help="Maximum seconds for --wait.",
)
def qexec_command(
    project: Path,
    submission_id: str,
    wait_for_result: bool,
    timeout: int,
) -> None:
    """Reconcile one governed IBM job into a signed QEXEC receipt."""

    try:
        context = _load_chain(project, submission_id)

        if context["existing"] is not None:
            click.secho(
                "[STATUS] QEXEC ALREADY EXISTS",
                fg="green",
                bold=True,
            )
            print(f"Receipt: {context['existing']}")
            return

        print("=== QuantumD IBM Execution Reconciliation ===")
        print(f"Submission:           {submission_id}")
        print(f"Plan:                 {context['plan_id']}")
        print(f"Approval:             {context['approval_id']}")
        print(f"IBM job ID:           {context['job_id']}")
        print(f"Backend:              {context['binding']['backend']}")
        print(f"Authorized shots:     {context['binding']['shots']}")
        print()

        labels = [
            "QPLAN signature and artifacts",
            "QAPPROVAL signature and binding",
            "QSUB signature and IBM job ID",
            "Consumed single-use approval",
            "Submission within approval window",
        ]
        for number, label in enumerate(labels, start=1):
            click.secho(
                f"[CHECK {number}] {label:.<42} PASS",
                fg="green",
            )

        service = _service(context)
        job = service.job(context["job_id"])

        _require("Retrieved IBM job ID", job.job_id(), context["job_id"])
        _require(
            "Retrieved IBM backend",
            _job_backend_name(job),
            context["binding"]["backend"],
        )

        primitive = _runtime_value(getattr(job, "primitive_id", None))
        if primitive is not None:
            if str(primitive).lower() not in {"sampler", "samplerv2"}:
                raise ReconciliationError(
                    f"Unexpected IBM primitive: {primitive!r}"
                )

        status = str(job.status()).upper()
        print(f"\nIBM job status:       {status}")

        if status in {"INITIALIZING", "QUEUED", "RUNNING"}:
            if not wait_for_result:
                click.secho(
                    "\n[STATUS] IBM JOB NOT TERMINAL",
                    fg="yellow",
                    bold=True,
                )
                print("QEXEC created:        False")
                print(
                    "Rerun with --wait to reconcile when "
                    "the IBM job reaches a terminal state."
                )
                return
            result = job.result(timeout=timeout)
            status = str(job.status()).upper()
        elif status == "DONE":
            result = job.result(timeout=timeout)
        else:
            result = None

        metadata = _job_metadata(job)

        if status in {"ERROR", "CANCELLED"}:
            error_message = None
            try:
                error_message = job.error_message()
            except Exception:
                pass

            execution_id, receipt = _terminal_failure_receipt(
                context,
                status,
                error_message,
                metadata,
            )
            execution_dir = (
                context["project"]
                / "evidence"
                / "executions"
                / execution_id
            )
            receipt_path = execution_dir / "receipt.json"
            _write_json(receipt_path, receipt)

            click.secho(
                "\n[STATUS] TERMINAL IBM FAILURE ATTESTED",
                fg="red",
                bold=True,
            )
            print(f"Execution ID:         {execution_id}")
            print(f"IBM status:           {status}")
            print(f"Receipt:              {receipt_path}")
            return

        _require("Final IBM job status", status, "DONE")

        try:
            from qiskit_ibm_runtime import RuntimeDecoder, RuntimeEncoder
        except ImportError as exc:
            raise ReconciliationError(
                "Runtime result encoders are unavailable."
            ) from exc

        result_bytes = (
            json.dumps(
                result,
                cls=RuntimeEncoder,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")

        try:
            json.loads(
                result_bytes.decode("utf-8"),
                cls=RuntimeDecoder,
            )
        except Exception as exc:
            raise ReconciliationError(
                "Runtime result failed a save/load verification."
            ) from exc

        counts = _counts_from_result(result)
        observed_shots = sum(counts.values())
        _require(
            "Observed result shots",
            observed_shots,
            context["binding"]["shots"],
        )

        created = datetime.now(timezone.utc)
        execution_id = (
            f"QEXEC-{created:%Y%m%d}-{uuid.uuid4().hex[:8]}"
        )
        execution_dir = (
            context["project"]
            / "evidence"
            / "executions"
            / execution_id
        )
        result_path = execution_dir / "result.json"
        counts_path = execution_dir / "counts.json"
        metrics_path = execution_dir / "job-metadata.json"

        _write_bytes(result_path, result_bytes)
        _write_json(
            counts_path,
            {
                "counts": counts,
                "observed_shots": observed_shots,
            },
        )
        _write_json(metrics_path, metadata)

        receipt_payload = {
            "schema_version": "quantumd.ai/execution/v0.1",
            "execution_id": execution_id,
            "created_at": created.isoformat(),
            "status": "EXECUTION_COMPLETED",
            "submission_id": context["submission_id"],
            "plan_id": context["plan_id"],
            "approval_id": context["approval_id"],
            "chain": {
                "plan_file_sha256": _sha256_bytes(
                    context["plan_raw"]
                ),
                "approval_file_sha256": _sha256_bytes(
                    context["approval_raw"]
                ),
                "submission_file_sha256": _sha256_bytes(
                    context["submission_raw"]
                ),
                "consumption_file_sha256": _sha256_bytes(
                    context["consumption_raw"]
                ),
                "isa_circuit_sha256": (
                    context["binding"]["isa_circuit_sha256"]
                ),
                "target_snapshot_sha256": (
                    context["binding"]["target_snapshot_sha256"]
                ),
            },
            "ibm": {
                "job_id": context["job_id"],
                "job_status": status,
                "backend": context["binding"]["backend"],
                "primitive": context["binding"]["primitive"],
                "shots_authorized": context["binding"]["shots"],
                "shots_observed": observed_shots,
                "metadata_artifact": {
                    "artifact": "job-metadata.json",
                    "sha256": _sha256_file(metrics_path),
                },
            },
            "results": {
                "runtime_result": {
                    "artifact": "result.json",
                    "format": "Qiskit RuntimeEncoder JSON",
                    "sha256": _sha256_file(result_path),
                    "round_trip_verified": True,
                },
                "counts": {
                    "artifact": "counts.json",
                    "sha256": _sha256_file(counts_path),
                    "values": counts,
                },
            },
            "hardware_submitted": True,
            "terminal": True,
        }

        context["approval_key"] = context["approval_key"]
        receipt = attest(receipt_payload, context)
        receipt_path = execution_dir / "receipt.json"
        _write_json(receipt_path, receipt)

        click.secho(
            "\n[STATUS] EXECUTION COMPLETED AND ATTESTED",
            fg="green",
            bold=True,
        )
        print(f"Execution ID:         {execution_id}")
        print(f"Submission ID:        {context['submission_id']}")
        print(f"IBM job ID:           {context['job_id']}")
        print(f"Backend:              {context['binding']['backend']}")
        print(f"Shots verified:       {observed_shots}")
        print(f"Counts:               {counts}")
        print(f"Receipt:              {receipt_path}")

    except Exception as exc:
        click.secho(
            "\n[STATUS] QEXEC RECONCILIATION DENIED",
            fg="red",
            bold=True,
        )
        print(f"  └─ {type(exc).__name__}: {exc}")
        raise click.exceptions.Exit(1) from exc


qexec = qexec_command

