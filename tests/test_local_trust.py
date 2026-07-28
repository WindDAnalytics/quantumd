from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import (
    hashes,
    serialization,
)
from cryptography.hazmat.primitives.asymmetric import (
    ec,
    utils,
)

from quantumd.local_trust import (
    HARDWARE_AUTHORIZATION,
    PROVIDER,
    SIGNATURE_STATUS,
    exists,
    initialize,
    inspect,
    sign_digest,
)


def test_local_trust_initializes_idempotently(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    (project / "evidence").mkdir(parents=True)

    first = initialize(project)
    second = initialize(project)

    assert first == second
    assert exists(project)
    assert first["provider"] == PROVIDER
    assert (
        first["hardware_authorization"]
        == HARDWARE_AUTHORIZATION
    )
    assert first["permitted_targets"] == [
        "aer-simulator"
    ]

    private_path = Path(
        first["private_key_path"]
    )
    assert private_path.is_file()
    assert private_path.stat().st_mode & 0o777 == 0o600

    cached_path = Path(
        first["cached_public_key_path"]
    )
    assert cached_path.is_file()


def test_local_trust_signs_prehashed_digest(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    (project / "evidence").mkdir(parents=True)

    trust = initialize(project)
    digest = hashlib.sha256(
        b"quantumd-local-development"
    ).digest()

    result = sign_digest(
        digest.hex(),
        project,
    )

    assert result["signed"] is True
    assert (
        result["signature_status"]
        == SIGNATURE_STATUS
    )
    assert result["provider"] == PROVIDER
    assert (
        result["hardware_authorization"]
        == "PROHIBITED"
    )

    public_key = (
        serialization.load_pem_public_key(
            Path(
                trust["public_key_path"]
            ).read_bytes()
        )
    )

    assert isinstance(
        public_key,
        ec.EllipticCurvePublicKey,
    )

    public_key.verify(
        base64.b64decode(
            result["value_base64"],
            validate=True,
        ),
        digest,
        ec.ECDSA(
            utils.Prehashed(hashes.SHA256())
        ),
    )


def test_local_trust_refuses_partial_state(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    root = project / ".quantumd" / "local-trust"
    (project / "evidence").mkdir(parents=True)
    root.mkdir(parents=True)

    (root / "trust.json").write_text(
        json.dumps({"partial": True}),
        encoding="utf-8",
    )

    with pytest.raises(
        RuntimeError,
        match="partially configured",
    ):
        initialize(project)


def test_local_trust_detects_broad_key_permissions(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    (project / "evidence").mkdir(parents=True)

    trust = initialize(project)
    private_path = Path(
        trust["private_key_path"]
    )
    private_path.chmod(0o644)

    with pytest.raises(
        PermissionError,
        match="permissions are too broad",
    ):
        inspect(project)
