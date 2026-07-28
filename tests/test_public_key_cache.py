from __future__ import annotations

import json
from pathlib import Path

import pytest

from quantumd.evidence.signing import (
    cache_verified_public_key,
)


PEM_ONE = (
    b"-----BEGIN PUBLIC KEY-----\n"
    b"PHASE4B-KEY-ONE\n"
    b"-----END PUBLIC KEY-----\n"
)

PEM_TWO = (
    b"-----BEGIN PUBLIC KEY-----\n"
    b"PHASE4B-KEY-TWO\n"
    b"-----END PUBLIC KEY-----\n"
)


def test_cache_verified_public_key_creates_versioned_and_active_files(
    tmp_path: Path,
) -> None:
    evidence_root = tmp_path / "evidence"
    key_version = "projects/test/keyVersions/1"

    result = cache_verified_public_key(
        evidence_root,
        key_version,
        PEM_ONE,
    )

    active = Path(result["active_public_key"])
    versioned = Path(result["versioned_public_key"])
    metadata = Path(result["metadata"])

    assert active.read_bytes() == PEM_ONE
    assert versioned.read_bytes() == PEM_ONE

    metadata_value = json.loads(
        metadata.read_text(encoding="utf-8")
    )

    assert metadata_value["key_version"] == key_version
    assert (
        metadata_value["public_key_sha256"]
        == result["public_key_sha256"]
    )


def test_cache_verified_public_key_is_idempotent(
    tmp_path: Path,
) -> None:
    evidence_root = tmp_path / "evidence"
    key_version = "projects/test/keyVersions/1"

    first = cache_verified_public_key(
        evidence_root,
        key_version,
        PEM_ONE,
    )
    second = cache_verified_public_key(
        evidence_root,
        key_version,
        PEM_ONE,
    )

    assert first == second


def test_cache_rejects_conflicting_bytes_for_same_key_version(
    tmp_path: Path,
) -> None:
    evidence_root = tmp_path / "evidence"
    key_version = "projects/test/keyVersions/1"

    cache_verified_public_key(
        evidence_root,
        key_version,
        PEM_ONE,
    )

    with pytest.raises(RuntimeError):
        cache_verified_public_key(
            evidence_root,
            key_version,
            PEM_TWO,
        )


def test_active_key_advances_on_key_rotation(
    tmp_path: Path,
) -> None:
    evidence_root = tmp_path / "evidence"

    first = cache_verified_public_key(
        evidence_root,
        "projects/test/keyVersions/1",
        PEM_ONE,
    )

    second = cache_verified_public_key(
        evidence_root,
        "projects/test/keyVersions/2",
        PEM_TWO,
    )

    assert (
        Path(second["active_public_key"]).read_bytes()
        == PEM_TWO
    )
    assert (
        Path(first["versioned_public_key"]).read_bytes()
        == PEM_ONE
    )
    assert (
        Path(second["versioned_public_key"]).read_bytes()
        == PEM_TWO
    )
