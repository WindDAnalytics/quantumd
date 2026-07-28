import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import crcmod.predefined
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from google.cloud import kms


def _crc32c(data: bytes) -> int:
    """Calculate the Castagnoli CRC32C checksum required by Cloud KMS."""
    checksum = crcmod.predefined.mkPredefinedCrcFun("crc-32c")
    return checksum(data)


def _integer_value(value: Any) -> int:
    """Handle either a protobuf wrapper or a plain integer."""
    return int(getattr(value, "value", value))


# QUANTUMD_PHASE4B_PUBLIC_KEY_CACHE
def _atomic_replace_bytes(
    path: Path,
    data: bytes,
    *,
    mode: int = 0o444,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.tmp"
    )

    try:
        file_descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )

        with os.fdopen(file_descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())

        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _write_once_or_require_identical(
    path: Path,
    data: bytes,
    *,
    mode: int = 0o444,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        file_descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            mode,
        )
    except FileExistsError:
        existing = path.read_bytes()

        if existing != data:
            raise RuntimeError(
                "Refusing to replace cached public-key material "
                f"with different bytes: {path}"
            )

        return

    with os.fdopen(file_descriptor, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def cache_verified_public_key(
    evidence_root: Path,
    key_version_name: str,
    pem_bytes: bytes,
    *,
    algorithm: str = "EC_SIGN_P256_SHA256",
) -> dict[str, str]:
    # Persist a verified KMS public key for offline verification.
    # The versioned copy is immutable; the root copy tracks rotations.
    if not isinstance(evidence_root, Path):
        evidence_root = Path(evidence_root)

    evidence_root = evidence_root.expanduser().resolve()

    if not key_version_name:
        raise ValueError("KMS key-version name cannot be empty.")

    if not pem_bytes:
        raise ValueError("Public-key PEM cannot be empty.")

    key_version_fingerprint = hashlib.sha256(
        key_version_name.encode("utf-8")
    ).hexdigest()[:24]

    pem_sha256 = hashlib.sha256(pem_bytes).hexdigest()

    key_dir = (
        evidence_root
        / "keys"
        / key_version_fingerprint
    )
    versioned_key_path = key_dir / "public-key.pem"
    metadata_path = key_dir / "metadata.json"
    active_key_path = evidence_root / "public-key.pem"

    metadata = {
        "algorithm": algorithm,
        "key_version": key_version_name,
        "key_version_fingerprint": key_version_fingerprint,
        "public_key_sha256": pem_sha256,
        "schema_version": "quantumd.ai/public-key-cache/v0.1",
    }

    metadata_bytes = (
        json.dumps(
            metadata,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")

    _write_once_or_require_identical(
        versioned_key_path,
        pem_bytes,
    )
    _write_once_or_require_identical(
        metadata_path,
        metadata_bytes,
    )

    if (
        not active_key_path.exists()
        or active_key_path.read_bytes() != pem_bytes
    ):
        _atomic_replace_bytes(
            active_key_path,
            pem_bytes,
        )

    return {
        "active_public_key": str(active_key_path),
        "key_version_fingerprint": key_version_fingerprint,
        "metadata": str(metadata_path),
        "public_key_sha256": pem_sha256,
        "versioned_public_key": str(versioned_key_path),
    }


def sign_payload_with_kms(
    payload_hash_hex: str,
    key_version_name: str,
    evidence_root: Path | None = None,
) -> dict:
    """
    Sign a precomputed SHA-256 digest with Cloud KMS and independently
    verify the returned ECDSA signature using the KMS public key.
    """
    try:
        digest_bytes = bytes.fromhex(payload_hash_hex)

        if len(digest_bytes) != 32:
            raise ValueError(
                "EC_SIGN_P256_SHA256 requires a 32-byte SHA-256 digest."
            )

        client = kms.KeyManagementServiceClient()
        digest_crc32c = _crc32c(digest_bytes)

        response = client.asymmetric_sign(
            request={
                "name": key_version_name,
                "digest": {"sha256": digest_bytes},
                "digest_crc32c": digest_crc32c,
            }
        )

        # Confirm Cloud KMS used the intended key version.
        if response.name != key_version_name:
            raise RuntimeError(
                "Cloud KMS returned a different key-version resource name."
            )

        # Confirm KMS received and checked the digest checksum.
        if not response.verified_digest_crc32c:
            raise RuntimeError(
                "Cloud KMS did not verify the request digest CRC32C."
            )

        # Confirm the signature was not corrupted in transit.
        returned_signature_crc32c = _integer_value(
            response.signature_crc32c
        )
        calculated_signature_crc32c = _crc32c(response.signature)

        if returned_signature_crc32c != calculated_signature_crc32c:
            raise RuntimeError(
                "Cloud KMS signature CRC32C verification failed."
            )

        # Retrieve the public key belonging to the exact signing version.
        public_key_response = client.get_public_key(
            request={"name": key_version_name}
        )

        if public_key_response.name != key_version_name:
            raise RuntimeError(
                "Cloud KMS returned a public key for a different key version."
            )

        expected_algorithm = (
            kms.CryptoKeyVersion.CryptoKeyVersionAlgorithm
            .EC_SIGN_P256_SHA256
        )

        if public_key_response.algorithm != expected_algorithm:
            raise RuntimeError(
                "Unexpected KMS key algorithm: "
                f"{public_key_response.algorithm!s}"
            )

        pem_bytes = public_key_response.pem.encode("utf-8")

        returned_pem_crc32c = _integer_value(
            public_key_response.pem_crc32c
        )
        calculated_pem_crc32c = _crc32c(pem_bytes)

        if returned_pem_crc32c != calculated_pem_crc32c:
            raise RuntimeError(
                "Cloud KMS public-key PEM CRC32C verification failed."
            )

        public_key = serialization.load_pem_public_key(pem_bytes)

        if not isinstance(public_key, ec.EllipticCurvePublicKey):
            raise TypeError(
                "Cloud KMS returned a non-elliptic-curve public key."
            )

        # KMS signed the existing SHA-256 digest, so use Prehashed to avoid
        # hashing the digest a second time.
        public_key.verify(
            response.signature,
            digest_bytes,
            ec.ECDSA(utils.Prehashed(hashes.SHA256())),
        )

        cache_metadata = None

        if evidence_root is not None:
            cache_metadata = cache_verified_public_key(
                evidence_root,
                key_version_name,
                pem_bytes,
            )

        return {
            "provider": "gcp-cloud-kms",
            "algorithm": "EC_SIGN_P256_SHA256",
            "key_version": key_version_name,
            "value_base64": base64.b64encode(
                response.signature
            ).decode("utf-8"),
            "signature_status": "KMS_SIGNED",
            "provider_response_integrity_verified": True,
            "public_key_response_integrity_verified": True,
            "public_key_signature_verified": True,
            "public_key_sha256": hashlib.sha256(
                pem_bytes
            ).hexdigest(),
            "public_key_cached": cache_metadata is not None,
            "signed": True,
        }

    except InvalidSignature:
        return {
            "signed": False,
            "signature_status": "PUBLIC_KEY_VERIFICATION_FAILED",
            "provider_response_integrity_verified": True,
            "public_key_signature_verified": False,
            "error_type": "InvalidSignature",
            "error_message": (
                "The KMS signature did not verify against the "
                "retrieved public key."
            ),
        }

    except Exception as exc:
        return {
            "signed": False,
            "signature_status": "FAILED",
            "provider_response_integrity_verified": False,
            "public_key_signature_verified": False,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }
