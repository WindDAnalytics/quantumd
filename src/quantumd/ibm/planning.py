from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any

from qiskit import qpy
from qiskit.transpiler import generate_preset_pass_manager
from qiskit_ibm_runtime import QiskitRuntimeService

from quantumd.evidence.signing import sign_payload_with_kms
from quantumd.ibm.secrets import access_secret


PLAN_SCHEMA = "quantumd.ai/plan/v0.1"


def _canonical_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _make_read_only(path: Path) -> None:
    path.chmod(0o444)


def _latest_trusted_execution(
    project_dir: Path,
) -> tuple[Path, dict[str, Any]]:
    root = project_dir / "evidence" / "executions"

    if not root.is_dir():
        raise RuntimeError(
            f"No execution evidence directory found: {root}"
        )

    receipts = sorted(
        root.glob("QEXEC-*/receipt.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )

    for receipt_path in receipts:
        receipt = json.loads(
            receipt_path.read_text(encoding="utf-8")
        )
        integrity = receipt.get("integrity", {})
        authorization = receipt.get("authorization", {})
        logical_qpy = receipt_path.parent / "logical-circuit.qpy"

        trusted = (
            receipt.get("status") == "EXECUTION_COMPLETED"
            and integrity.get("signed") is True
            and integrity.get("signature_status") == "KMS_SIGNED"
            and integrity.get(
                "public_key_signature_verified"
            )
            is True
            and authorization.get("signature_verified") is True
            and logical_qpy.is_file()
        )

        if not trusted:
            continue

        expected_hash = (
            receipt.get("workload", {})
            .get("logical_circuit", {})
            .get("sha256")
        )

        if not expected_hash:
            continue

        if _sha256_file(logical_qpy) != expected_hash:
            continue

        return receipt_path, receipt

    raise RuntimeError(
        "No fully attested execution with a valid logical QPY "
        "artifact was found."
    )


def _load_single_qpy(path: Path):
    with path.open("rb") as handle:
        circuits = qpy.load(handle)

    if len(circuits) != 1:
        raise RuntimeError(
            f"Expected one logical circuit; found {len(circuits)}."
        )

    return circuits[0]


def _operation_counts(circuit) -> dict[str, int]:
    return {
        str(name): int(count)
        for name, count in circuit.count_ops().items()
    }


def _target_snapshot(backend) -> dict[str, Any]:
    coupling_map = backend.coupling_map

    edges: list[list[int]] = []
    if coupling_map is not None:
        edges = sorted(
            [int(left), int(right)]
            for left, right in coupling_map.get_edges()
        )

    return {
        "backend": str(backend.name),
        "backend_version": str(backend.backend_version),
        "num_qubits": int(backend.num_qubits),
        "operation_names": sorted(
            str(name) for name in backend.operation_names
        ),
        "coupling_map": edges,
        "dt": getattr(backend, "dt", None),
        "dtm": getattr(backend, "dtm", None),
    }


def create_ibm_plan(
    project_dir: Path,
    target: str,
    shots: int,
    seed: int = 1729,
    optimization_level: int = 1,
) -> Path:
    project_dir = project_dir.resolve()

    if not target.startswith("ibm:"):
        raise ValueError(
            "IBM targets must use the form ibm:<backend-name>."
        )

    backend_name = target.split(":", 1)[1].strip()

    if not backend_name.startswith("ibm_"):
        raise ValueError(
            "Physical IBM backend names must begin with 'ibm_'."
        )

    if shots < 1:
        raise ValueError("Shots must be at least 1.")

    if optimization_level not in {0, 1, 2, 3}:
        raise ValueError(
            "Optimization level must be 0, 1, 2, or 3."
        )

    kms_key = os.environ.get("QUANTUMD_KMS_KEY_VERSION")
    if not kms_key:
        raise RuntimeError(
            "QUANTUMD_KMS_KEY_VERSION is not configured."
        )

    instance = os.environ.get(
        "QUANTUMD_IBM_INSTANCE",
        "open-instance",
    )

    receipt_path, receipt = _latest_trusted_execution(
        project_dir
    )
    logical_qpy = receipt_path.parent / "logical-circuit.qpy"
    logical_circuit = _load_single_qpy(logical_qpy)

    secret = access_secret("quantumd-ibm-api-key")

    service = QiskitRuntimeService(
        token=secret.value,
        instance=instance,
    )

    backend = service.backend(backend_name)
    backend_status = backend.status()

    if not backend_status.operational:
        raise RuntimeError(
            f"IBM backend {backend_name!r} is not operational."
        )

    target_snapshot = _target_snapshot(backend)

    pass_manager = generate_preset_pass_manager(
        backend=backend,
        optimization_level=optimization_level,
        seed_transpiler=seed,
    )
    isa_circuit = pass_manager.run(logical_circuit)

    timestamp = datetime.now(timezone.utc)
    plan_id = (
        f"QPLAN-{timestamp:%Y%m%d}-"
        f"{uuid.uuid4().hex[:8]}"
    )

    plans_root = project_dir / "evidence" / "plans"
    plans_root.mkdir(parents=True, exist_ok=True)

    final_dir = plans_root / plan_id
    temp_dir = plans_root / f".{plan_id}.tmp"
    temp_dir.mkdir(parents=False, exist_ok=False)

    try:
        logical_out = temp_dir / "logical-circuit.qpy"
        isa_out = temp_dir / "isa-circuit.qpy"
        target_out = temp_dir / "backend-target.json"

        shutil.copyfile(logical_qpy, logical_out)

        with isa_out.open("wb") as handle:
            qpy.dump(isa_circuit, handle)

        _write_json(target_out, target_snapshot)
        target_hash = _sha256_file(target_out)

        upstream_receipt_hash = _sha256_file(receipt_path)

        plan: dict[str, Any] = {
            "schema_version": PLAN_SCHEMA,
            "plan_id": plan_id,
            "status": "PLANNED",
            "created_at": timestamp.isoformat(),
            "hardware_submitted": False,
            "authorization": {
                "verification_run_id": (
                    receipt.get("authorization", {}).get(
                        "verification_run_id"
                    )
                ),
                "signature_verified": True,
            },
            "upstream_execution": {
                "receipt": str(
                    receipt_path.relative_to(project_dir)
                ),
                "receipt_sha256": upstream_receipt_hash,
                "execution_id": receipt.get("execution_id"),
            },
            "workload": {
                "source_sha256": (
                    receipt.get("workload", {}).get(
                        "source_sha256"
                    )
                ),
                "manifest_sha256": (
                    receipt.get("workload", {}).get(
                        "manifest_sha256"
                    )
                ),
                "logical_circuit": {
                    "artifact": "logical-circuit.qpy",
                    "format": "QPY",
                    "sha256": _sha256_file(logical_out),
                    "num_qubits": int(
                        logical_circuit.num_qubits
                    ),
                    "depth": int(logical_circuit.depth()),
                    "operations": _operation_counts(
                        logical_circuit
                    ),
                },
                "isa_circuit": {
                    "artifact": "isa-circuit.qpy",
                    "format": "QPY",
                    "sha256": _sha256_file(isa_out),
                    "num_qubits": int(
                        isa_circuit.num_qubits
                    ),
                    "depth": int(isa_circuit.depth()),
                    "operations": _operation_counts(
                        isa_circuit
                    ),
                    "layout": str(isa_circuit.layout),
                },
            },
            "target": {
                "provider": "ibm-quantum-platform",
                "backend": str(backend.name),
                "backend_version": str(
                    backend.backend_version
                ),
                "instance": instance,
                "hardware": True,
                "primitive": "SamplerV2",
                "target_snapshot": {
                    "artifact": "backend-target.json",
                    "sha256": target_hash,
                },
                "observation": {
                    "operational": bool(
                        backend_status.operational
                    ),
                    "pending_jobs": int(
                        backend_status.pending_jobs
                    ),
                    "status_message": str(
                        backend_status.status_msg
                    ),
                    "retrieved_at": datetime.now(
                        timezone.utc
                    ).isoformat(),
                },
            },
            "execution_parameters": {
                "shots": int(shots),
                "transpiler_seed": int(seed),
                "optimization_level": int(
                    optimization_level
                ),
            },
            "credentials": {
                "secret_id": "quantumd-ibm-api-key",
                "secret_version": secret.version_name,
                "secret_value_persisted": False,
            },
            "software": {
                "qiskit": version("qiskit"),
                "qiskit_aer": version("qiskit-aer"),
                "qiskit_ibm_runtime": version(
                    "qiskit-ibm-runtime"
                ),
            },
        }

        plan_hash = _sha256_bytes(_canonical_bytes(plan))
        signature = sign_payload_with_kms(
            plan_hash,
            kms_key,
        )

        if not (
            signature.get("signed") is True
            and signature.get(
                "public_key_signature_verified"
            )
            is True
        ):
            raise RuntimeError(
                "QPLAN KMS signing or public-key verification "
                f"failed: {signature}"
            )

        plan["integrity"] = {
            "canonical_payload_sha256": plan_hash,
            **signature,
        }

        plan_path = temp_dir / "plan.json"
        _write_json(plan_path, plan)

        for artifact in (
            logical_out,
            isa_out,
            target_out,
            plan_path,
        ):
            _make_read_only(artifact)

        os.replace(temp_dir, final_dir)

    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise

    return final_dir / "plan.json"
