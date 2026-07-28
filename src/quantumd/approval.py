"""Cryptographically governed human approval for signed QuantumD plans."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import click


class ApprovalError(RuntimeError):
    """Raised when a plan cannot safely be approved."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _relative_to_project(path: Path, project: Path) -> str:
    try:
        return path.resolve().relative_to(project.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _canonical_variants(payload: dict[str, Any]) -> list[tuple[str, bytes]]:
    """Return supported deterministic JSON encodings.

    Existing QuantumD artifacts may have been created by slightly different
    JSON serialization helpers. Every accepted representation remains sorted
    and deterministic.
    """

    variants: list[tuple[str, bytes]] = [
        (
            "compact-utf8",
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8"),
        ),
        (
            "compact-ascii",
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8"),
        ),
        (
            "standard-utf8",
            json.dumps(
                payload,
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8"),
        ),
        (
            "indented-utf8",
            json.dumps(
                payload,
                sort_keys=True,
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8"),
        ),
        (
            "indented-utf8-newline",
            (
                json.dumps(
                    payload,
                    sort_keys=True,
                    indent=2,
                    ensure_ascii=False,
                    allow_nan=False,
                )
                + "\n"
            ).encode("utf-8"),
        ),
    ]

    unique: list[tuple[str, bytes]] = []
    seen: set[bytes] = set()

    for name, data in variants:
        if data not in seen:
            seen.add(data)
            unique.append((name, data))

    return unique


def _matching_plan_payload(plan: dict[str, Any]) -> tuple[bytes, str]:
    """Reconstruct and validate the exact signed plan payload."""

    integrity = plan.get("integrity")

    if not isinstance(integrity, dict):
        raise ApprovalError("Plan has no integrity record.")

    expected = integrity.get("canonical_payload_sha256")

    if not isinstance(expected, str) or len(expected) != 64:
        raise ApprovalError("Plan canonical payload hash is missing or invalid.")

    payload_without_integrity = copy.deepcopy(plan)
    payload_without_integrity.pop("integrity", None)

    payload_shapes: list[tuple[str, dict[str, Any]]] = [
        ("without-integrity", payload_without_integrity),
    ]

    # Compatibility candidate for an implementation that signed basic
    # integrity metadata but excluded the resulting digest and signature.
    integrity_metadata = {
        key: integrity[key]
        for key in ("algorithm", "key_version", "provider")
        if key in integrity
    }

    if integrity_metadata:
        payload_with_metadata = copy.deepcopy(payload_without_integrity)
        payload_with_metadata["integrity"] = integrity_metadata
        payload_shapes.append(("with-integrity-metadata", payload_with_metadata))

    attempts: list[str] = []

    for shape_name, payload in payload_shapes:
        for encoding_name, data in _canonical_variants(payload):
            actual = _sha256_bytes(data)
            attempts.append(f"{shape_name}/{encoding_name}={actual}")

            if actual == expected:
                return data, f"{shape_name}/{encoding_name}"

    attempted = "\n  ".join(attempts)

    raise ApprovalError(
        "Plan payload does not reproduce its signed canonical hash.\n"
        "Approval refused because the signed payload cannot be independently "
        "reconstructed.\n"
        f"Expected: {expected}\n"
        f"Attempted:\n  {attempted}"
    )


def _crc32c(data: bytes) -> int:
    try:
        import google_crc32c
    except ImportError as exc:
        raise ApprovalError(
            "google-crc32c is required for KMS transport-integrity checks."
        ) from exc

    return int(google_crc32c.value(data))


def _load_kms_client() -> Any:
    try:
        from google.cloud import kms_v1
    except ImportError as exc:
        raise ApprovalError(
            "google-cloud-kms is required for governed approval signing."
        ) from exc

    return kms_v1.KeyManagementServiceClient()


def _get_verified_public_key(
    client: Any,
    key_version: str,
) -> tuple[bytes, bool]:
    response = client.get_public_key(
        request={"name": key_version}
    )

    pem = response.pem.encode("utf-8")
    expected_crc = int(response.pem_crc32c)
    actual_crc = _crc32c(pem)

    if expected_crc != actual_crc:
        raise ApprovalError(
            "KMS public-key CRC32C verification failed."
        )

    return pem, True


def _verify_ecdsa_signature(
    public_key_pem: bytes,
    signature: bytes,
    digest: bytes,
) -> None:
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec, utils
    except ImportError as exc:
        raise ApprovalError(
            "cryptography is required for independent signature verification."
        ) from exc

    public_key = serialization.load_pem_public_key(public_key_pem)

    if not isinstance(public_key, ec.EllipticCurvePublicKey):
        raise ApprovalError("KMS public key is not an EC public key.")

    public_key.verify(
        signature,
        digest,
        ec.ECDSA(utils.Prehashed(hashes.SHA256())),
    )


def _verify_plan_signature(
    client: Any,
    plan: dict[str, Any],
) -> tuple[bytes, str, bytes]:
    integrity = plan["integrity"]

    if integrity.get("signed") is not True:
        raise ApprovalError("Plan is not marked as signed.")

    if integrity.get("signature_status") != "KMS_SIGNED":
        raise ApprovalError("Plan does not have KMS_SIGNED status.")

    if integrity.get("algorithm") != "EC_SIGN_P256_SHA256":
        raise ApprovalError(
            "Unsupported plan signature algorithm: "
            f"{integrity.get('algorithm')!r}"
        )

    key_version = integrity.get("key_version")
    signature_base64 = integrity.get("value_base64")

    if not isinstance(key_version, str) or not key_version:
        raise ApprovalError("Plan KMS key version is missing.")

    if not isinstance(signature_base64, str) or not signature_base64:
        raise ApprovalError("Plan signature is missing.")

    try:
        signature = base64.b64decode(
            signature_base64,
            validate=True,
        )
    except Exception as exc:
        raise ApprovalError("Plan signature is not valid Base64.") from exc

    payload_bytes, encoding_name = _matching_plan_payload(plan)
    digest = hashlib.sha256(payload_bytes).digest()

    public_key_pem, _ = _get_verified_public_key(
        client,
        key_version,
    )

    try:
        _verify_ecdsa_signature(
            public_key_pem,
            signature,
            digest,
        )
    except Exception as exc:
        raise ApprovalError(
            "Independent public-key verification of QPLAN failed."
        ) from exc

    return public_key_pem, encoding_name, signature


def _safe_artifact_path(plan_dir: Path, artifact_name: str) -> Path:
    artifact = (plan_dir / artifact_name).resolve()

    try:
        artifact.relative_to(plan_dir.resolve())
    except ValueError as exc:
        raise ApprovalError(
            f"Artifact escapes its plan directory: {artifact_name}"
        ) from exc

    return artifact


def _verify_artifact(
    plan_dir: Path,
    descriptor: dict[str, Any],
    label: str,
) -> dict[str, str]:
    artifact_name = descriptor.get("artifact")
    expected_hash = descriptor.get("sha256")

    if not isinstance(artifact_name, str) or not artifact_name:
        raise ApprovalError(f"{label} artifact name is missing.")

    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        raise ApprovalError(f"{label} SHA-256 is missing or invalid.")

    artifact_path = _safe_artifact_path(
        plan_dir,
        artifact_name,
    )

    if not artifact_path.is_file():
        raise ApprovalError(
            f"{label} artifact does not exist: {artifact_path}"
        )

    actual_hash = _sha256_file(artifact_path)

    if actual_hash != expected_hash:
        raise ApprovalError(
            f"{label} artifact hash mismatch.\n"
            f"Expected: {expected_hash}\n"
            f"Actual:   {actual_hash}"
        )

    return {
        "artifact": artifact_name,
        "sha256": actual_hash,
    }


def _discover_approver() -> str | None:
    commands = [
        ["gcloud", "config", "get-value", "account"],
        ["git", "config", "user.email"],
    ]

    for command in commands:
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            continue

        value = result.stdout.strip()

        if (
            result.returncode == 0
            and value
            and value not in {"(unset)", "None"}
        ):
            return value

    return os.environ.get("USER")


def _sign_digest(
    client: Any,
    key_version: str,
    digest: bytes,
) -> tuple[bytes, bool]:
    digest_crc32c = _crc32c(digest)

    response = client.asymmetric_sign(
        request={
            "name": key_version,
            "digest": {"sha256": digest},
            "digest_crc32c": digest_crc32c,
        }
    )

    if response.verified_digest_crc32c is not True:
        raise ApprovalError(
            "KMS did not verify the approval digest CRC32C."
        )

    signature = bytes(response.signature)

    if _crc32c(signature) != int(response.signature_crc32c):
        raise ApprovalError(
            "KMS approval signature CRC32C verification failed."
        )

    return signature, True


@click.command("approve")
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
    "--plan-id",
    required=True,
    help="Exact signed QPLAN identifier to approve.",
)
@click.option(
    "--approver",
    help="Human or service identity granting approval.",
)
@click.option(
    "--reason",
    required=True,
    help="Human-readable reason for granting approval.",
)
@click.option(
    "--ttl-minutes",
    type=click.IntRange(min=1, max=1440),
    default=30,
    show_default=True,
    help="How long this approval may authorize submission.",
)
@click.option(
    "--yes",
    is_flag=True,
    help="Skip the typed confirmation challenge.",
)
def approve_command(
    project: Path,
    plan_id: str,
    approver: str | None,
    reason: str,
    ttl_minutes: int,
    yes: bool,
) -> None:
    """Approve one exact, signed, non-submitted quantum execution plan."""

    try:
        project = project.resolve()
        plan_dir = project / "evidence" / "plans" / plan_id
        plan_path = plan_dir / "plan.json"

        if not plan_path.is_file():
            raise ApprovalError(
                f"Plan not found: {plan_path}"
            )

        raw_plan = plan_path.read_bytes()

        try:
            plan = json.loads(raw_plan)
        except json.JSONDecodeError as exc:
            raise ApprovalError("Plan is not valid JSON.") from exc

        if plan.get("plan_id") != plan_id:
            raise ApprovalError(
                "Requested plan ID does not match plan.json."
            )

        if plan.get("schema_version") != "quantumd.ai/plan/v0.1":
            raise ApprovalError(
                "Unsupported QPLAN schema: "
                f"{plan.get('schema_version')!r}"
            )

        if plan.get("status") != "PLANNED":
            raise ApprovalError(
                f"Plan status is not PLANNED: {plan.get('status')!r}"
            )

        if plan.get("hardware_submitted") is not False:
            raise ApprovalError(
                "Plan does not prove hardware_submitted=False."
            )

        authorization = plan.get("authorization", {})

        if authorization.get("signature_verified") is not True:
            raise ApprovalError(
                "Upstream authorization was not signature verified."
            )

        target = plan.get("target", {})

        if target.get("hardware") is not True:
            raise ApprovalError(
                "Approval currently requires a physical hardware target."
            )

        credentials = plan.get("credentials", {})

        if credentials.get("secret_value_persisted") is not False:
            raise ApprovalError(
                "Plan does not prove that secret material was excluded."
            )

        parameters = plan.get("execution_parameters", {})
        shots = parameters.get("shots")

        if not isinstance(shots, int) or shots <= 0:
            raise ApprovalError("Plan shot count is invalid.")

        workload = plan.get("workload", {})

        logical_artifact = _verify_artifact(
            plan_dir,
            workload.get("logical_circuit", {}),
            "Logical circuit",
        )

        isa_artifact = _verify_artifact(
            plan_dir,
            workload.get("isa_circuit", {}),
            "ISA circuit",
        )

        target_snapshot = _verify_artifact(
            plan_dir,
            target.get("target_snapshot", {}),
            "Backend target snapshot",
        )

        kms_client = _load_kms_client()

        (
            public_key_pem,
            canonical_encoding,
            plan_signature,
        ) = _verify_plan_signature(
            kms_client,
            plan,
        )

        approver_identity = approver or _discover_approver()

        if not approver_identity:
            approver_identity = click.prompt(
                "Approver identity",
                type=str,
            ).strip()

        if not approver_identity:
            raise ApprovalError("Approver identity cannot be empty.")

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=ttl_minutes)

        plan_file_hash = _sha256_bytes(raw_plan)
        plan_payload_hash = plan["integrity"][
            "canonical_payload_sha256"
        ]
        key_version = plan["integrity"]["key_version"]

        approval_id = (
            f"QAPPROVAL-{now:%Y%m%d}-{uuid.uuid4().hex[:8]}"
        )

        binding = {
            "plan_id": plan_id,
            "plan_artifact": _relative_to_project(
                plan_path,
                project,
            ),
            "plan_file_sha256": plan_file_hash,
            "plan_canonical_payload_sha256": plan_payload_hash,
            "plan_signature_sha256": _sha256_bytes(plan_signature),
            "plan_signature_key_version": key_version,
            "plan_canonical_encoding": canonical_encoding,
            "authorization_verification_run_id": authorization.get(
                "verification_run_id"
            ),
            "provider": target.get("provider"),
            "backend": target.get("backend"),
            "backend_version": target.get("backend_version"),
            "instance": target.get("instance"),
            "primitive": target.get("primitive"),
            "target_snapshot": target_snapshot,
            "logical_circuit": logical_artifact,
            "isa_circuit": isa_artifact,
            "manifest_sha256": workload.get("manifest_sha256"),
            "source_sha256": workload.get("source_sha256"),
            "shots": shots,
            "optimization_level": parameters.get(
                "optimization_level"
            ),
            "transpiler_seed": parameters.get("transpiler_seed"),
            "secret_id": credentials.get("secret_id"),
            "secret_version": credentials.get("secret_version"),
            "secret_value_persisted": False,
            "hardware_submitted_at_approval": False,
        }

        approval_payload = {
            "schema_version": "quantumd.ai/approval/v0.1",
            "approval_id": approval_id,
            "created_at": now.isoformat(),
            "status": "APPROVED",
            "decision": "APPROVE",
            "approver": {
                "identity": approver_identity,
                "reason": reason,
                "confirmation_method": (
                    "noninteractive-yes"
                    if yes
                    else "typed-plan-id-challenge"
                ),
            },
            "authorization_scope": {
                "action": "SUBMIT_IBM_QPU_JOB",
                "single_use": True,
                "not_before": now.isoformat(),
                "expires_at": expires_at.isoformat(),
            },
            "binding": binding,
        }

        click.echo(
            "=== QuantumD Cryptographic Human Approval ==="
        )
        click.echo(f"Plan:                 {plan_id}")
        click.echo(
            f"Backend:              {target.get('backend')}"
        )
        click.echo(
            f"Backend version:      {target.get('backend_version')}"
        )
        click.echo(f"Shots:                {shots}")
        click.echo(
            f"ISA circuit SHA-256:  {isa_artifact['sha256']}"
        )
        click.echo(
            f"Target snapshot:      {target_snapshot['sha256']}"
        )
        click.echo(
            f"Secret version:       {credentials.get('secret_version')}"
        )
        click.echo(f"Approver:             {approver_identity}")
        click.echo(
            f"Approval expires:     {expires_at.isoformat()}"
        )
        click.echo("Hardware submitted:   False")
        click.echo()

        click.secho(
            "[CHECK 1] Canonical plan payload........ PASS",
            fg="green",
        )
        click.secho(
            "[CHECK 2] Independent QPLAN signature... PASS",
            fg="green",
        )
        click.secho(
            "[CHECK 3] Logical circuit artifact...... PASS",
            fg="green",
        )
        click.secho(
            "[CHECK 4] ISA circuit artifact.......... PASS",
            fg="green",
        )
        click.secho(
            "[CHECK 5] Backend target snapshot........ PASS",
            fg="green",
        )
        click.secho(
            "[CHECK 6] No persisted secret value...... PASS",
            fg="green",
        )

        if not yes:
            click.echo()
            expected_challenge = f"APPROVE {plan_id}"
            entered = click.prompt(
                f"Type exactly '{expected_challenge}'",
                type=str,
            )

            if entered != expected_challenge:
                raise ApprovalError(
                    "Typed approval challenge did not match."
                )

        approval_bytes = json.dumps(
            approval_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")

        approval_digest = hashlib.sha256(
            approval_bytes
        ).digest()

        approval_signature, response_crc_verified = _sign_digest(
            kms_client,
            key_version,
            approval_digest,
        )

        _verify_ecdsa_signature(
            public_key_pem,
            approval_signature,
            approval_digest,
        )

        approval = copy.deepcopy(approval_payload)
        approval["integrity"] = {
            "algorithm": "EC_SIGN_P256_SHA256",
            "canonical_payload_sha256": approval_digest.hex(),
            "key_version": key_version,
            "provider": "gcp-cloud-kms",
            "provider_response_integrity_verified": (
                response_crc_verified
            ),
            "public_key_response_integrity_verified": True,
            "public_key_sha256": _sha256_bytes(public_key_pem),
            "public_key_signature_verified": True,
            "signature_status": "KMS_SIGNED",
            "signed": True,
            "value_base64": base64.b64encode(
                approval_signature
            ).decode("ascii"),
        }

        approval_dir = (
            project
            / "evidence"
            / "approvals"
            / approval_id
        )

        approval_dir.mkdir(
            parents=True,
            exist_ok=False,
        )

        approval_path = approval_dir / "approval.json"
        signature_path = approval_dir / "signature.der"
        public_key_path = approval_dir / "public-key.pem"

        temporary_path = approval_dir / ".approval.json.tmp"

        temporary_path.write_text(
            json.dumps(
                approval,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

        temporary_path.replace(approval_path)
        signature_path.write_bytes(approval_signature)
        public_key_path.write_bytes(public_key_pem)

        for artifact_path in (
            approval_path,
            signature_path,
            public_key_path,
        ):
            os.chmod(artifact_path, 0o444)

        click.echo()
        click.secho(
            "[STATUS] APPROVAL CREATED AND ATTESTED",
            fg="green",
            bold=True,
        )
        click.echo(f"Approval ID:          {approval_id}")
        click.echo(
            "Approval artifact:    "
            f"{_relative_to_project(approval_path, project)}"
        )
        click.echo(
            f"Approval payload hash:{approval_digest.hex()}"
        )
        click.echo(
            "Hardware submitted:   False"
        )

    except ApprovalError as exc:
        click.echo()
        click.secho(
            "[STATUS] APPROVAL DENIED",
            fg="red",
            bold=True,
        )
        click.echo(f"  └─ {exc}")
        raise click.exceptions.Exit(1) from exc
    except Exception as exc:
        click.echo()
        click.secho(
            "[STATUS] APPROVAL FAILED CLOSED",
            fg="red",
            bold=True,
        )
        click.echo(
            f"  └─ {type(exc).__name__}: {exc}"
        )
        raise click.exceptions.Exit(1) from exc


# Public Click command exported for CLI registration.
approve = approve_command
