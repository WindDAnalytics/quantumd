from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

from quantumd.evidence.signing import cache_verified_public_key


PROVIDER = "quantumd-local-development"
SIGNATURE_STATUS = "LOCAL_DEVELOPMENT_SIGNED"
TRUST_MODE = "LOCAL_DEVELOPMENT"
TRUST_SCOPE = "LOCAL_SIMULATION_ONLY"
HARDWARE_AUTHORIZATION = "PROHIBITED"


def _paths(project_dir: str | Path) -> dict[str, Path]:
    project = Path(project_dir).expanduser().resolve()
    root = project / ".quantumd" / "local-trust"
    return {
        "project": project,
        "root": root,
        "private": root / "private-key.pem",
        "public": root / "public-key.pem",
        "metadata": root / "trust.json",
    }


def _atomic_write(path: Path, data: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.tmp"
    )

    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )

        with os.fdopen(descriptor, "wb") as handle:
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


def _public_pem(
    private_key: ec.EllipticCurvePrivateKey,
) -> bytes:
    return private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def _key_version(public_pem: bytes) -> str:
    digest = hashlib.sha256(public_pem).hexdigest()[:24]
    return f"quantumd-local-development:{digest}"


def exists(project_dir: str | Path) -> bool:
    return _paths(project_dir)["metadata"].is_file()


def initialize(project_dir: str | Path) -> dict[str, Any]:
    paths = _paths(project_dir)
    project = paths["project"]

    if not project.is_dir():
        raise FileNotFoundError(
            f"Project directory not found: {project}"
        )

    present = [
        paths["private"].exists(),
        paths["public"].exists(),
        paths["metadata"].exists(),
    ]

    if any(present):
        if not all(present):
            raise RuntimeError(
                "Local trust is partially configured; refusing "
                "to regenerate or replace key material."
            )
        return inspect(project)

    private_key = ec.generate_private_key(ec.SECP256R1())

    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )

    public_pem = _public_pem(private_key)
    key_version = _key_version(public_pem)
    public_sha256 = hashlib.sha256(public_pem).hexdigest()

    metadata = {
        "algorithm": "EC_SIGN_P256_SHA256",
        "hardware_authorization": HARDWARE_AUTHORIZATION,
        "key_version": key_version,
        "permitted_targets": ["aer-simulator"],
        "provider": PROVIDER,
        "public_key_sha256": public_sha256,
        "schema_version": (
            "quantumd.ai/local-development-trust/v0.1"
        ),
        "trust_mode": TRUST_MODE,
        "trust_scope": TRUST_SCOPE,
    }

    _atomic_write(
        paths["private"],
        private_pem,
        0o600,
    )
    _atomic_write(
        paths["public"],
        public_pem,
        0o444,
    )
    _atomic_write(
        paths["metadata"],
        (
            json.dumps(
                metadata,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8"),
        0o444,
    )

    cache_verified_public_key(
        project / "evidence",
        key_version,
        public_pem,
    )

    return inspect(project)


def inspect(project_dir: str | Path) -> dict[str, Any]:
    paths = _paths(project_dir)

    for name in ("private", "public", "metadata"):
        if not paths[name].is_file():
            raise FileNotFoundError(
                f"Local trust file missing: {paths[name]}"
            )

    metadata = json.loads(
        paths["metadata"].read_text(encoding="utf-8")
    )

    expected = {
        "algorithm": "EC_SIGN_P256_SHA256",
        "hardware_authorization": (
            HARDWARE_AUTHORIZATION
        ),
        "provider": PROVIDER,
        "trust_mode": TRUST_MODE,
        "trust_scope": TRUST_SCOPE,
    }

    for field, value in expected.items():
        if metadata.get(field) != value:
            raise RuntimeError(
                f"Invalid local trust metadata: {field}"
            )

    if metadata.get("permitted_targets") != [
        "aer-simulator"
    ]:
        raise RuntimeError(
            "Local trust must permit only aer-simulator."
        )

    private_mode = (
        paths["private"].stat().st_mode & 0o777
    )

    if private_mode & 0o077:
        raise PermissionError(
            "Local private key permissions are too broad: "
            f"{private_mode:04o}"
        )

    private_key = serialization.load_pem_private_key(
        paths["private"].read_bytes(),
        password=None,
    )

    if not isinstance(
        private_key,
        ec.EllipticCurvePrivateKey,
    ):
        raise TypeError(
            "Local private key is not elliptic-curve."
        )

    if not isinstance(
        private_key.curve,
        ec.SECP256R1,
    ):
        raise TypeError(
            "Local private key must use P-256."
        )

    public_pem = paths["public"].read_bytes()

    if _public_pem(private_key) != public_pem:
        raise RuntimeError(
            "Local public key does not match private key."
        )

    public_sha256 = hashlib.sha256(
        public_pem
    ).hexdigest()

    if (
        metadata.get("public_key_sha256")
        != public_sha256
    ):
        raise RuntimeError(
            "Local public-key hash mismatch."
        )

    if (
        metadata.get("key_version")
        != _key_version(public_pem)
    ):
        raise RuntimeError(
            "Local key-version mismatch."
        )

    cached = cache_verified_public_key(
        paths["project"] / "evidence",
        metadata["key_version"],
        public_pem,
    )

    return {
        **metadata,
        "private_key_path": str(
            paths["private"]
        ),
        "public_key_path": str(
            paths["public"]
        ),
        "cached_public_key_path": (
            cached["versioned_public_key"]
        ),
    }


def sign_digest(
    payload_hash_hex: str,
    project_dir: str | Path,
) -> dict[str, Any]:
    try:
        digest = bytes.fromhex(payload_hash_hex)

        if len(digest) != 32:
            raise ValueError(
                "Expected a 32-byte SHA-256 digest."
            )

        trust = inspect(project_dir)

        private_key = (
            serialization.load_pem_private_key(
                Path(
                    trust["private_key_path"]
                ).read_bytes(),
                password=None,
            )
        )

        if not isinstance(
            private_key,
            ec.EllipticCurvePrivateKey,
        ):
            raise TypeError(
                "Local private key is not EC."
            )

        signature = private_key.sign(
            digest,
            ec.ECDSA(
                utils.Prehashed(hashes.SHA256())
            ),
        )

        private_key.public_key().verify(
            signature,
            digest,
            ec.ECDSA(
                utils.Prehashed(hashes.SHA256())
            ),
        )

        return {
            "algorithm": "EC_SIGN_P256_SHA256",
            "hardware_authorization": (
                HARDWARE_AUTHORIZATION
            ),
            "key_version": trust["key_version"],
            "provider": PROVIDER,
            "public_key_cached": True,
            "public_key_sha256": (
                trust["public_key_sha256"]
            ),
            "public_key_signature_verified": True,
            "signature_status": SIGNATURE_STATUS,
            "signed": True,
            "trust_mode": TRUST_MODE,
            "trust_scope": TRUST_SCOPE,
            "value_base64": base64.b64encode(
                signature
            ).decode("ascii"),
        }

    except Exception as exc:
        return {
            "error_message": str(exc),
            "error_type": type(exc).__name__,
            "provider": PROVIDER,
            "signature_status": (
                "LOCAL_DEVELOPMENT_SIGNING_FAILED"
            ),
            "signed": False,
            "trust_mode": TRUST_MODE,
            "trust_scope": TRUST_SCOPE,
        }
