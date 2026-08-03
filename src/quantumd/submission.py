"""Fail-closed submission of an exactly approved IBM QPU workload."""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click

from quantumd.approval import (
    ApprovalError,
    _get_verified_public_key,
    _load_kms_client,
    _relative_to_project,
    _sha256_bytes,
    _sha256_file,
    _sign_digest,
    _verify_artifact,
    _verify_ecdsa_signature,
    _verify_plan_signature,
)


class SubmissionError(RuntimeError):
    """Raised when a governed submission must be denied."""


def canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def now() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: Any, label: str) -> datetime:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise SubmissionError(f"{label} is invalid.") from exc
    if result.tzinfo is None:
        raise SubmissionError(f"{label} has no timezone.")
    return result.astimezone(timezone.utc)


def require(label: str, actual: Any, expected: Any) -> None:
    if actual != expected:
        raise SubmissionError(
            f"{label} mismatch.\nExpected: {expected!r}\nActual:   {actual!r}"
        )


def read_json(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    if not path.is_file():
        raise SubmissionError(f"{label} not found: {path}")
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SubmissionError(f"{label} is invalid JSON.") from exc
    if not isinstance(value, dict):
        raise SubmissionError(f"{label} is not a JSON object.")
    return raw, value


def approval_signature(
    client: Any,
    approval: dict[str, Any],
) -> tuple[bytes, bytes]:
    integrity = approval.get("integrity", {})
    require("Approval signed", integrity.get("signed"), True)
    require(
        "Approval signature status",
        integrity.get("signature_status"),
        "KMS_SIGNED",
    )
    require(
        "Approval algorithm",
        integrity.get("algorithm"),
        "EC_SIGN_P256_SHA256",
    )

    payload = copy.deepcopy(approval)
    payload.pop("integrity", None)
    payload_bytes = canonical(payload)
    require(
        "Approval canonical hash",
        _sha256_bytes(payload_bytes),
        integrity.get("canonical_payload_sha256"),
    )

    try:
        signature = base64.b64decode(
            integrity["value_base64"],
            validate=True,
        )
    except Exception as exc:
        raise SubmissionError(
            "Approval signature is invalid Base64."
        ) from exc

    public_key, _ = _get_verified_public_key(
        client,
        integrity["key_version"],
    )
    try:
        _verify_ecdsa_signature(
            public_key,
            signature,
            hashlib.sha256(payload_bytes).digest(),
        )
    except Exception as exc:
        raise SubmissionError(
            "Approval signature verification failed."
        ) from exc

    declared = integrity.get("public_key_sha256")
    if declared:
        require(
            "Approval public key hash",
            _sha256_bytes(public_key),
            declared,
        )
    return signature, public_key


def approval_window(approval: dict[str, Any]) -> datetime:
    scope = approval.get("authorization_scope", {})
    require(
        "Approval action",
        scope.get("action"),
        "SUBMIT_IBM_QPU_JOB",
    )
    require(
        "Approval single use",
        scope.get("single_use"),
        True,
    )
    start = parse_time(scope.get("not_before"), "not_before")
    end = parse_time(scope.get("expires_at"), "expires_at")
    current = now()
    if current < start:
        raise SubmissionError(
            f"Approval is not active until {start.isoformat()}."
        )
    if current >= end:
        raise SubmissionError(
            f"Approval expired at {end.isoformat()}."
        )
    return end


def local_preflight(
    project: Path,
    approval_id: str,
) -> dict[str, Any]:
    project = project.resolve()
    approval_dir = (
        project / "evidence" / "approvals" / approval_id
    )
    approval_path = approval_dir / "approval.json"
    approval_raw, approval = read_json(
        approval_path,
        "Approval",
    )

    require(
        "Approval ID",
        approval.get("approval_id"),
        approval_id,
    )
    require(
        "Approval schema",
        approval.get("schema_version"),
        "quantumd.ai/approval/v0.1",
    )
    require(
        "Approval status",
        approval.get("status"),
        "APPROVED",
    )
    require(
        "Approval decision",
        approval.get("decision"),
        "APPROVE",
    )
    approval_window(approval)

    binding = approval.get("binding", {})
    plan_id = binding.get("plan_id")
    if (
        not isinstance(plan_id, str)
        or not plan_id.startswith("QPLAN-")
    ):
        raise SubmissionError(
            "Approval has an invalid plan ID."
        )

    plan_dir = project / "evidence" / "plans" / plan_id
    plan_path = plan_dir / "plan.json"
    plan_raw, plan = read_json(plan_path, "Plan")

    require("Plan ID", plan.get("plan_id"), plan_id)
    require(
        "Plan schema",
        plan.get("schema_version"),
        "quantumd.ai/plan/v0.1",
    )
    require(
        "Plan status",
        plan.get("status"),
        "PLANNED",
    )
    require(
        "Plan hardware submitted",
        plan.get("hardware_submitted"),
        False,
    )

    client = _load_kms_client()
    try:
        plan_key, encoding, plan_sig = (
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
        snapshot = _verify_artifact(
            plan_dir,
            plan["target"]["target_snapshot"],
            "Backend target snapshot",
        )
    except ApprovalError as exc:
        raise SubmissionError(str(exc)) from exc

    approval_sig, approval_key = approval_signature(
        client,
        approval,
    )
    require(
        "Plan and approval KMS key",
        approval["integrity"]["key_version"],
        plan["integrity"]["key_version"],
    )

    target = plan["target"]
    workload = plan["workload"]
    params = plan["execution_parameters"]
    credentials = plan["credentials"]
    authorization = plan["authorization"]

    derived = {
        "plan_id": plan_id,
        "plan_artifact": _relative_to_project(
            plan_path,
            project,
        ),
        "plan_file_sha256": _sha256_bytes(plan_raw),
        "plan_canonical_payload_sha256": (
            plan["integrity"]["canonical_payload_sha256"]
        ),
        "plan_signature_sha256": _sha256_bytes(plan_sig),
        "plan_signature_key_version": (
            plan["integrity"]["key_version"]
        ),
        "plan_canonical_encoding": encoding,
        "authorization_verification_run_id": (
            authorization.get("verification_run_id")
        ),
        "provider": target.get("provider"),
        "backend": target.get("backend"),
        "backend_version": target.get(
            "backend_version"
        ),
        "instance": target.get("instance"),
        "primitive": target.get("primitive"),
        "target_snapshot": snapshot,
        "logical_circuit": logical,
        "isa_circuit": isa,
        "manifest_sha256": workload.get(
            "manifest_sha256"
        ),
        "source_sha256": workload.get(
            "source_sha256"
        ),
        "shots": params.get("shots"),
        "optimization_level": params.get(
            "optimization_level"
        ),
        "transpiler_seed": params.get(
            "transpiler_seed"
        ),
        "secret_id": credentials.get("secret_id"),
        "secret_version": credentials.get(
            "secret_version"
        ),
        "secret_value_persisted": False,
        "hardware_submitted_at_approval": False,
    }

    require(
        "Complete approval binding",
        binding,
        derived,
    )
    require(
        "Authorization signature",
        authorization.get("signature_verified"),
        True,
    )
    require(
        "Hardware target",
        target.get("hardware"),
        True,
    )
    require(
        "Primitive",
        target.get("primitive"),
        "SamplerV2",
    )
    require(
        "Secret persistence",
        credentials.get("secret_value_persisted"),
        False,
    )

    consumption = approval_dir / "consumption.json"
    if consumption.exists():
        _, used = read_json(
            consumption,
            "Approval consumption",
        )
        raise SubmissionError(
            "Approval already claimed or consumed: "
            f"{used.get('status')!r}, "
            f"{used.get('submission_id')!r}"
        )

    isa_path = plan_dir / isa["artifact"]
    isa_bytes = isa_path.read_bytes()
    require(
        "ISA bytes",
        _sha256_bytes(isa_bytes),
        isa["sha256"],
    )
    _, snapshot_value = read_json(
        plan_dir / snapshot["artifact"],
        "Target snapshot",
    )

    return {
        "project": project,
        "approval_id": approval_id,
        "approval_dir": approval_dir,
        "approval_path": approval_path,
        "approval_raw": approval_raw,
        "approval": approval,
        "approval_signature": approval_sig,
        "approval_key": approval_key,
        "plan_id": plan_id,
        "plan_dir": plan_dir,
        "plan_path": plan_path,
        "plan_raw": plan_raw,
        "plan": plan,
        "plan_key": plan_key,
        "plan_signature": plan_sig,
        "isa_bytes": isa_bytes,
        "snapshot": snapshot_value,
        "consumption": consumption,
        "client": client,
    }


def secret(secret_version: str) -> str:
    try:
        import google_crc32c
        from google.cloud import secretmanager
    except ImportError as exc:
        raise SubmissionError(
            "google-cloud-secret-manager and "
            "google-crc32c are required."
        ) from exc

    response = (
        secretmanager.SecretManagerServiceClient()
        .access_secret_version(
            request={"name": secret_version}
        )
    )
    data = bytes(response.payload.data)
    require(
        "Secret Manager CRC32C",
        int(google_crc32c.value(data)),
        int(response.payload.data_crc32c),
    )
    value = data.decode("utf-8").strip()
    if not value:
        raise SubmissionError(
            "IBM credential secret is empty."
        )
    return value


def backend_name(backend: Any) -> str:
    value = getattr(backend, "name", None)
    return value() if callable(value) else str(value)


def backend_version(backend: Any) -> str:
    candidates = [
        getattr(backend, "backend_version", None),
        getattr(backend, "version", None),
    ]
    try:
        candidates.append(
            getattr(
                backend.configuration(),
                "backend_version",
                None,
            )
        )
    except Exception:
        pass

    for value in candidates:
        value = value() if callable(value) else value
        if value is not None:
            return str(value)

    raise SubmissionError(
        "IBM backend version is unavailable."
    )


def live_backend(
    context: dict[str, Any],
) -> dict[str, Any]:
    try:
        from qiskit_ibm_runtime import (
            QiskitRuntimeService,
        )
        from quantumd.ibm.planning import (
            _target_snapshot,
        )
    except ImportError as exc:
        raise SubmissionError(
            "IBM Runtime support is unavailable."
        ) from exc

    target = context["plan"]["target"]
    token = secret(
        context["plan"]["credentials"][
            "secret_version"
        ]
    )
    try:
        service = QiskitRuntimeService(
            channel="ibm_quantum_platform",
            token=token,
            instance=target.get("instance"),
        )
    finally:
        token = None

    backend = service.backend(target["backend"])
    require(
        "Live backend",
        backend_name(backend),
        target["backend"],
    )
    require(
        "Live backend version",
        backend_version(backend),
        str(target["backend_version"]),
    )

    current = _target_snapshot(backend)
    if current != context["snapshot"]:
        raise SubmissionError(
            "Live IBM target differs from the approved "
            "snapshot. Create a new plan and approval."
        )

    return {
        "service": service,
        "backend": backend,
        "snapshot": current,
    }


def attest(
    payload: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    data = canonical(payload)
    digest = hashlib.sha256(data).digest()
    key_version = (
        context["approval"]["integrity"]["key_version"]
    )
    signature, crc_ok = _sign_digest(
        context["client"],
        key_version,
        digest,
    )
    _verify_ecdsa_signature(
        context["approval_key"],
        signature,
        digest,
    )

    value = copy.deepcopy(payload)
    value["integrity"] = {
        "algorithm": "EC_SIGN_P256_SHA256",
        "canonical_payload_sha256": digest.hex(),
        "key_version": key_version,
        "provider": "gcp-cloud-kms",
        "provider_response_integrity_verified": (
            crc_ok
        ),
        "public_key_response_integrity_verified": True,
        "public_key_sha256": _sha256_bytes(
            context["approval_key"]
        ),
        "public_key_signature_verified": True,
        "signature_status": "KMS_SIGNED",
        "signed": True,
        "value_base64": base64.b64encode(
            signature
        ).decode("ascii"),
    }
    return value


def write_json(
    path: Path,
    value: dict[str, Any],
    exclusive: bool = False,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if exclusive:
        try:
            fd = os.open(
                path,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL,
                0o444,
            )
        except FileExistsError as exc:
            raise SubmissionError(
                "Approval was claimed concurrently."
            ) from exc

        with os.fdopen(
            fd,
            "w",
            encoding="utf-8",
        ) as handle:
            json.dump(
                value,
                handle,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        return

    temp = path.with_name(
        f".{path.name}.{uuid.uuid4().hex}.tmp"
    )
    with temp.open(
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(
            value,
            handle,
            indent=2,
            sort_keys=True,
        )
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())

    os.chmod(temp, 0o444)
    os.replace(temp, path)


def show(context: dict[str, Any]) -> None:
    binding = context["approval"]["binding"]

    print(
        "=== QuantumD Governed IBM Submission ==="
    )
    print(
        f"Plan:                 "
        f"{context['plan_id']}"
    )
    print(
        f"Approval:             "
        f"{context['approval_id']}"
    )
    print(
        f"Backend:              "
        f"{binding['backend']}"
    )
    print(
        f"Backend version:      "
        f"{binding['backend_version']}"
    )
    print(
        f"Shots:                "
        f"{binding['shots']}"
    )
    print(
        "ISA circuit SHA-256:  "
        f"{binding['isa_circuit']['sha256']}"
    )
    print(
        "Target snapshot:      "
        f"{binding['target_snapshot']['sha256']}"
    )
    print(
        f"Secret version:       "
        f"{binding['secret_version']}"
    )
    print(
        "Approval expires:     "
        f"{context['approval']['authorization_scope']['expires_at']}"
    )
    print("Hardware submitted:   False\n")

    labels = [
        "QPLAN signature and payload",
        "QAPPROVAL signature and payload",
        "Exact plan-to-approval binding",
        "Circuit and target artifacts",
        "Backend, shots, secret version",
        "Fresh, unused approval",
        "No persisted secret value",
    ]

    for number, label in enumerate(
        labels,
        start=1,
    ):
        click.secho(
            f"[CHECK {number}] "
            f"{label:.<42} PASS",
            fg="green",
        )


@click.command("submit")
@click.argument(
    "project",
    type=click.Path(
        exists=True,
        file_okay=False,
        path_type=Path,
    ),
)
@click.option(
    "--approval-id",
    required=True,
)
@click.option(
    "--execute",
    is_flag=True,
    help=(
        "Submit the approved workload "
        "to IBM hardware."
    ),
)
@click.option(
    "--yes",
    is_flag=True,
)
def submit_command(
    project: Path,
    approval_id: str,
    execute: bool,
    yes: bool,
) -> None:
    """Verify and optionally submit one approved IBM QPU job."""

    context: dict[str, Any] | None = None
    submission_id: str | None = None
    submission_dir: Path | None = None
    claimed = False
    attempted = False

    try:
        context = local_preflight(
            project,
            approval_id,
        )
        show(context)

        if not execute:
            click.secho(
                "\n[STATUS] SUBMISSION PREFLIGHT READY",
                fg="green",
                bold=True,
            )
            print("Hardware submitted:   False")
            print(
                "Run again with --execute to cross "
                "the IBM hardware boundary."
            )
            return

        print(
            "\n[LIVE CHECK] Verifying the exact "
            "IBM backend and target..."
        )
        live = live_backend(context)
        click.secho(
            "[LIVE CHECK] Backend and target "
            "snapshot... PASS",
            fg="green",
        )
        approval_window(context["approval"])

        if not yes:
            challenge = f"SUBMIT {approval_id}"
            entered = click.prompt(
                f"Type exactly '{challenge}'"
            )
            if entered != challenge:
                raise SubmissionError(
                    "Typed challenge did not match."
                )

        expires_at = approval_window(
            context["approval"]
        )
        created = now()
        submission_id = (
            f"QSUB-{created:%Y%m%d}-"
            f"{uuid.uuid4().hex[:8]}"
        )
        submission_dir = (
            context["project"]
            / "evidence"
            / "submissions"
            / submission_id
        )
        submission_dir.mkdir(
            parents=True,
            exist_ok=False,
        )

        binding = context["approval"]["binding"]
        intent_payload = {
            "schema_version": (
                "quantumd.ai/submission-intent/v0.1"
            ),
            "submission_id": submission_id,
            "created_at": created.isoformat(),
            "status": "READY_TO_SUBMIT",
            "plan_id": context["plan_id"],
            "approval_id": approval_id,
            "binding": {
                "plan_file_sha256": _sha256_bytes(
                    context["plan_raw"]
                ),
                "plan_payload_sha256": (
                    context["plan"]["integrity"][
                        "canonical_payload_sha256"
                    ]
                ),
                "approval_file_sha256": (
                    _sha256_bytes(
                        context["approval_raw"]
                    )
                ),
                "approval_payload_sha256": (
                    context["approval"]["integrity"][
                        "canonical_payload_sha256"
                    ]
                ),
                "isa_circuit_sha256": (
                    binding["isa_circuit"]["sha256"]
                ),
                "target_snapshot_sha256": (
                    binding["target_snapshot"][
                        "sha256"
                    ]
                ),
                "provider": binding["provider"],
                "backend": binding["backend"],
                "backend_version": (
                    binding["backend_version"]
                ),
                "instance": binding["instance"],
                "primitive": binding["primitive"],
                "shots": binding["shots"],
                "secret_version": (
                    binding["secret_version"]
                ),
                "approval_expires_at": (
                    expires_at.isoformat()
                ),
            },
            "hardware_submitted": False,
        }

        intent = attest(
            intent_payload,
            context,
        )
        intent_path = (
            submission_dir / "intent.json"
        )
        write_json(
            intent_path,
            intent,
        )

        claimed_at = now()
        claim = {
            "schema_version": (
                "quantumd.ai/"
                "approval-consumption/v0.1"
            ),
            "approval_id": approval_id,
            "plan_id": context["plan_id"],
            "submission_id": submission_id,
            "claimed_at": claimed_at.isoformat(),
            "status": "CLAIMED",
            "single_use": True,
            "hardware_submission_attempted": False,
        }
        write_json(
            context["consumption"],
            attest(claim, context),
            exclusive=True,
        )
        claimed = True

        from qiskit import qpy
        from qiskit_ibm_runtime import SamplerV2

        circuits = qpy.load(
            io.BytesIO(context["isa_bytes"])
        )
        if len(circuits) != 1:
            raise SubmissionError(
                "ISA QPY must contain "
                "exactly one circuit."
            )

        circuit = circuits[0]
        require(
            "ISA qubit count",
            circuit.num_qubits,
            context["plan"]["workload"][
                "isa_circuit"
            ]["num_qubits"],
        )

        sampler = SamplerV2(
            mode=live["backend"]
        )

        click.secho(
            "\n[BOUNDARY] Submitting exact "
            "approved ISA circuit...",
            fg="yellow",
            bold=True,
        )

        attempted = True
        job = sampler.run(
            [circuit],
            shots=binding["shots"],
        )
        job_id = job.job_id()

        if not job_id:
            raise SubmissionError(
                "IBM returned no job ID."
            )

        accepted = now()
        submission_payload = {
            "schema_version": (
                "quantumd.ai/submission/v0.1"
            ),
            "submission_id": submission_id,
            "created_at": accepted.isoformat(),
            "status": "SUBMITTED",
            "plan_id": context["plan_id"],
            "approval_id": approval_id,
            "intent": {
                "artifact": _relative_to_project(
                    intent_path,
                    context["project"],
                ),
                "sha256": _sha256_file(
                    intent_path
                ),
                "canonical_payload_sha256": (
                    intent["integrity"][
                        "canonical_payload_sha256"
                    ]
                ),
            },
            "binding": intent_payload["binding"],
            "ibm": {
                "channel": (
                    "ibm_quantum_platform"
                ),
                "instance": binding["instance"],
                "backend": binding["backend"],
                "backend_version": (
                    backend_version(
                        live["backend"]
                    )
                ),
                "primitive": "SamplerV2",
                "job_id": job_id,
                "shots": binding["shots"],
            },
            "approval_consumption": {
                "single_use": True,
                "consumed_at": (
                    accepted.isoformat()
                ),
            },
            "hardware_submitted": True,
        }

        submission = attest(
            submission_payload,
            context,
        )
        submission_path = (
            submission_dir / "submission.json"
        )
        write_json(
            submission_path,
            submission,
        )

        consumed = {
            **claim,
            "status": "CONSUMED",
            "consumed_at": accepted.isoformat(),
            "hardware_submission_attempted": True,
            "hardware_submitted": True,
            "ibm_job_id": job_id,
            "submission_artifact": (
                _relative_to_project(
                    submission_path,
                    context["project"],
                )
            ),
            "submission_sha256": _sha256_file(
                submission_path
            ),
        }
        write_json(
            context["consumption"],
            attest(consumed, context),
        )

        click.secho(
            "\n[STATUS] IBM JOB SUBMITTED "
            "AND APPROVAL CONSUMED",
            fg="green",
            bold=True,
        )
        print(
            f"Submission ID:        "
            f"{submission_id}"
        )
        print(
            f"IBM job ID:           "
            f"{job_id}"
        )
        print(
            f"Backend:              "
            f"{binding['backend']}"
        )
        print(
            f"Shots:                "
            f"{binding['shots']}"
        )
        print(
            "Approval single-use:  CONSUMED"
        )
        print(
            "Hardware submitted:   True"
        )
        submission_artifact = _relative_to_project(
            submission_path,
            context["project"],
        )
        print(
            "Submission artifact:  "
            f"{submission_artifact}"
        )

    except Exception as exc:
        if (
            claimed
            and attempted
            and context
            and submission_id
            and submission_dir
        ):
            uncertain = {
                "schema_version": (
                    "quantumd.ai/"
                    "approval-consumption/v0.1"
                ),
                "approval_id": approval_id,
                "plan_id": context["plan_id"],
                "submission_id": submission_id,
                "updated_at": now().isoformat(),
                "status": "SUBMISSION_UNCERTAIN",
                "single_use": True,
                "hardware_submission_attempted": True,
                "hardware_submitted": "UNKNOWN",
                "retry_permitted": False,
                "error_type": type(exc).__name__,
                "reason": (
                    "The IBM call began but no durable "
                    "governed job record was completed. "
                    "Reconcile IBM jobs before further action."
                ),
            }

            write_json(
                context["consumption"],
                uncertain,
            )
            write_json(
                submission_dir / "failure.json",
                uncertain,
            )

        click.secho(
            "\n[STATUS] SUBMISSION DENIED",
            fg="red",
            bold=True,
        )
        print(
            f"  └─ {type(exc).__name__}: "
            f"{exc}"
        )
        raise click.exceptions.Exit(1) from exc


submit = submit_command

