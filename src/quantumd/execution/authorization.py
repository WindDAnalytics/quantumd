from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.hazmat.primitives.serialization import (
    load_pem_public_key,
)
from google.cloud import kms

from quantumd.evidence.builder import sha256_file
from quantumd.local_trust import (
    HARDWARE_AUTHORIZATION,
    PROVIDER as LOCAL_PROVIDER,
    SIGNATURE_STATUS as LOCAL_SIGNATURE_STATUS,
    TRUST_MODE as LOCAL_TRUST_MODE,
    TRUST_SCOPE as LOCAL_TRUST_SCOPE,
    inspect as inspect_local_trust,
)


class AuthorizationEngine:
    LOCAL_SIMULATION_DECISIONS = {
        "VERIFIED_FOR_EXECUTION",
        "VERIFIED_FOR_LOCAL_SIMULATION",
        "VERIFIED_EDUCATIONAL_ONLY",
    }

    QPU_DECISIONS = {
        "VERIFIED_FOR_EXECUTION",
        "VERIFIED_FOR_QPU_EXECUTION",
    }

    @staticmethod
    def _canonical_evidence(
        evidence: dict,
    ) -> tuple[bytes, str]:
        integrity = evidence.get("integrity", {})
        declared_hash = integrity.get(
            "canonical_payload_sha256"
        )

        stripped = dict(evidence)
        stripped["integrity"] = {}

        canonical = json.dumps(
            stripped,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

        actual_hash = hashlib.sha256(
            canonical
        ).hexdigest()

        if actual_hash != declared_hash:
            raise PermissionError(
                "EVIDENCE_COMPROMISED: Payload hash mismatch."
            )

        return canonical, actual_hash

    @staticmethod
    def _signature_bytes(
        integrity: dict,
    ) -> bytes:
        key_version = integrity.get("key_version")
        value_base64 = integrity.get("value_base64")

        if not key_version or not value_base64:
            raise PermissionError(
                "Incomplete signature metadata."
            )

        try:
            return base64.b64decode(
                value_base64,
                validate=True,
            )
        except Exception as exc:
            raise PermissionError(
                "Signature is invalid Base64."
            ) from exc

    @staticmethod
    def _verify_kms(
        integrity: dict,
        canonical: bytes,
    ) -> None:
        if integrity.get("signature_status") != "KMS_SIGNED":
            raise PermissionError(
                "KMS evidence does not have KMS_SIGNED status."
            )

        if (
            integrity.get("algorithm")
            != "EC_SIGN_P256_SHA256"
        ):
            raise PermissionError(
                "Unsupported KMS signature algorithm."
            )

        signature = AuthorizationEngine._signature_bytes(
            integrity
        )
        key_version = integrity["key_version"]

        client = kms.KeyManagementServiceClient()

        try:
            response = client.get_public_key(
                name=key_version
            )
            public_key = load_pem_public_key(
                response.pem.encode("utf-8")
            )
            public_key.verify(
                signature,
                canonical,
                ec.ECDSA(hashes.SHA256()),
            )
        except Exception as exc:
            raise PermissionError(
                "Cryptographic signature verification failed: "
                f"{exc}"
            ) from exc

    @staticmethod
    def _verify_local(
        project_dir: Path,
        integrity: dict,
        actual_hash: str,
        target: str,
    ) -> None:
        if target != "aer-simulator":
            raise PermissionError(
                "LOCAL_DEVELOPMENT_TRUST_SCOPE_VIOLATION: "
                "local trust authorizes only aer-simulator; "
                "IBM and all hardware/provider targets are "
                "prohibited."
            )

        required = {
            "algorithm": "EC_SIGN_P256_SHA256",
            "hardware_authorization": (
                HARDWARE_AUTHORIZATION
            ),
            "provider": LOCAL_PROVIDER,
            "signature_status": (
                LOCAL_SIGNATURE_STATUS
            ),
            "trust_mode": LOCAL_TRUST_MODE,
            "trust_scope": LOCAL_TRUST_SCOPE,
        }

        for field, expected in required.items():
            if integrity.get(field) != expected:
                raise PermissionError(
                    "Invalid local-development signature "
                    f"metadata: {field}."
                )

        trust = inspect_local_trust(project_dir)

        if (
            integrity.get("key_version")
            != trust["key_version"]
        ):
            raise PermissionError(
                "Local key-version lineage mismatch."
            )

        if (
            integrity.get("public_key_sha256")
            != trust["public_key_sha256"]
        ):
            raise PermissionError(
                "Local public-key hash mismatch."
            )

        signature = AuthorizationEngine._signature_bytes(
            integrity
        )

        public_key = load_pem_public_key(
            Path(
                trust["public_key_path"]
            ).read_bytes()
        )

        if not isinstance(
            public_key,
            ec.EllipticCurvePublicKey,
        ):
            raise PermissionError(
                "Local signing key is not elliptic-curve."
            )

        try:
            public_key.verify(
                signature,
                bytes.fromhex(actual_hash),
                ec.ECDSA(
                    utils.Prehashed(hashes.SHA256())
                ),
            )
        except Exception as exc:
            raise PermissionError(
                "Local-development signature verification "
                f"failed: {exc}"
            ) from exc

    @staticmethod
    def authorize(
        project_dir: Path,
        evidence_run: str,
        target: str,
    ) -> dict:
        project_dir = project_dir.resolve()
        record_path = (
            project_dir
            / "evidence"
            / "runs"
            / f"{evidence_run}.json"
        )

        if not record_path.exists():
            raise PermissionError(
                f"Evidence record {evidence_run} not found."
            )

        evidence = json.loads(
            record_path.read_text(encoding="utf-8")
        )

        integrity = evidence.get("integrity", {})

        if not integrity.get("signed"):
            raise PermissionError(
                "Evidence record is not signed."
            )

        canonical, actual_hash = (
            AuthorizationEngine._canonical_evidence(
                evidence
            )
        )

        provider = integrity.get("provider")
        status = integrity.get("signature_status")

        if (
            provider == "gcp-cloud-kms"
            or (
                provider is None
                and status == "KMS_SIGNED"
            )
        ):
            AuthorizationEngine._verify_kms(
                integrity,
                canonical,
            )
            trust_mode = "KMS_GOVERNED"
        elif provider == LOCAL_PROVIDER:
            AuthorizationEngine._verify_local(
                project_dir,
                integrity,
                actual_hash,
                target,
            )
            trust_mode = LOCAL_TRUST_MODE
        else:
            raise PermissionError(
                f"Unsupported signature provider: {provider!r}"
            )

        decision = evidence.get("final_decision", "")

        if target == "aer-simulator":
            if (
                decision
                not in AuthorizationEngine
                .LOCAL_SIMULATION_DECISIONS
            ):
                raise PermissionError(
                    "INSUFFICIENT_AUTHORIZATION: "
                    "Simulation requires one of "
                    f"{AuthorizationEngine.LOCAL_SIMULATION_DECISIONS}. "
                    f"Got: {decision}"
                )
        elif target.startswith("ibm:"):
            if (
                decision
                not in AuthorizationEngine.QPU_DECISIONS
            ):
                raise PermissionError(
                    "INSUFFICIENT_AUTHORIZATION: "
                    "QPU execution requires one of "
                    f"{AuthorizationEngine.QPU_DECISIONS}. "
                    f"Got: {decision}"
                )
        else:
            raise PermissionError(
                f"Unknown target: {target}"
            )

        return {
            "evidence": evidence,
            "payload_hash": actual_hash,
            "trust_mode": trust_mode,
        }

    @staticmethod
    def check_snapshot(
        snapshot_dir: Path,
        evidence: dict,
    ) -> None:
        manifest_hash = sha256_file(
            snapshot_dir / "experiment.yaml"
        )
        verified_manifest_hash = (
            evidence.get("hashes", {})
            .get("manifest_sha256")
        )

        if manifest_hash != verified_manifest_hash:
            raise PermissionError(
                "Manifest Identity Hash Mismatch. "
                f"Verified: {verified_manifest_hash} "
                f"Snapshot: {manifest_hash}"
            )

        source_info = (
            evidence.get("hashes", {})
            .get("source", {})
        )
        source_path = (
            snapshot_dir
            / source_info.get("path", "")
        )

        if not source_path.exists():
            raise PermissionError(
                "Verified source file missing from snapshot."
            )

        source_hash = sha256_file(source_path)

        if source_hash != source_info.get("sha256"):
            raise PermissionError(
                "Source Identity Hash Mismatch "
                "(Tampering detected). "
                f"Verified: {source_info.get('sha256')} "
                f"Snapshot: {source_hash}"
            )
