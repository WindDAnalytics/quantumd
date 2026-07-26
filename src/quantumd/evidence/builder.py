from __future__ import annotations

import hashlib
import json
import os
import uuid
import os
from quantumd.evidence.signing import sign_payload_with_kms
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


class EvidenceBuilder:
    """Build an append-only evidence record for one verification run."""

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir.resolve()

        timestamp_id = datetime.now(timezone.utc).strftime(
            "%Y%m%dT%H%M%S.%fZ"
        )
        self.run_id = f"{timestamp_id}-{uuid.uuid4().hex[:8]}"

        self.evidence_root = self.project_dir / "evidence"
        self.runs_dir = self.evidence_root / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)

        self.evidence: dict[str, Any] = {
            "schema_version": "quantumd.ai/evidence/v0.1",
            "run_id": self.run_id,
            "command": "verify",
            "started_at": utc_now(),
            "finalized_at": None,
            "project": {
                "name": self.project_dir.name,
                "path": str(self.project_dir),
            },
            "hashes": {},
            "gates": [],
            "final_decision": "PENDING",
            "integrity": {},
        }

    def set_manifest_hash(self, manifest_hash: str) -> None:
        if not manifest_hash:
            raise ValueError("Manifest hash cannot be empty.")

        self.evidence["hashes"]["manifest_sha256"] = manifest_hash

    def record_source_hash(self, source_path: Path) -> None:
        resolved_source = source_path.resolve()

        try:
            relative_source = resolved_source.relative_to(self.project_dir)
        except ValueError as exc:
            raise ValueError(
                "Entrypoint must remain inside the project directory."
            ) from exc

        if not resolved_source.is_file():
            raise FileNotFoundError(
                f"Entrypoint does not exist: {relative_source}"
            )

        self.evidence["hashes"]["source"] = {
            "path": relative_source.as_posix(),
            "sha256": sha256_file(resolved_source),
        }

    def add_gate_result(
        self,
        gate_name: str,
        status: str,
        details: Any = None,
    ) -> None:
        if status not in {"PASS", "FAIL", "ERROR", "SKIPPED", "CLASSICAL_BASELINE_MEETS_CONTRACT"}:
            raise ValueError(f"Unsupported gate status: {status}")

        self.evidence["gates"].append(
            {
                "gate": gate_name,
                "status": status,
                "recorded_at": utc_now(),
                "details": details,
            }
        )

    def finalize(self, decision: str) -> Path:
        if self.evidence["final_decision"] != "PENDING":
            raise RuntimeError("Evidence record has already been finalized.")

        self.evidence["final_decision"] = decision
        self.evidence["finalized_at"] = utc_now()

        # Hash the canonical evidence payload before adding the integrity field.
        canonical_payload = json.dumps(
            self.evidence,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

        evidence_hash = hashlib.sha256(canonical_payload).hexdigest()

        # Attempt GCP KMS Signature if configured
        kms_key = os.environ.get("QUANTUMD_KMS_KEY_VERSION")
        if kms_key:
            sig_data = sign_payload_with_kms(
                evidence_hash,
                kms_key,
                evidence_root=self.evidence_root,
            )
            self.evidence["integrity"] = {
                "canonical_payload_sha256": evidence_hash,
                **sig_data
            }
        else:
            self.evidence["integrity"] = {
                "canonical_payload_sha256": evidence_hash,
                "signed": False,
                "signature_status": "NO_KEY_PROVIDED",
            }

        filepath = self.runs_dir / f"{self.run_id}.json"
        rendered = json.dumps(
            self.evidence,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        ) + "\n"

        # O_EXCL guarantees an existing evidence record cannot be overwritten.
        file_descriptor = os.open(
            filepath,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o444,
        )

        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())

        # latest.json is only a mutable pointer, not the authoritative record.
        latest = self.evidence_root / "latest.json"
        temporary_latest = self.evidence_root / ".latest.json.tmp"

        pointer = {
            "run_id": self.run_id,
            "record": str(filepath.relative_to(self.project_dir)),
            "canonical_payload_sha256": evidence_hash,
            "final_decision": decision,
        }

        temporary_latest.write_text(
            json.dumps(pointer, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_latest, latest)

        return filepath
