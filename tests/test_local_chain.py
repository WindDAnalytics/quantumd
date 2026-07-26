from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from quantumd import chain


def _write_json(path: Path, value: dict) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    path.write_bytes(raw)
    return raw


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _build_local_chain(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict, Path]:
    manifest = project / "experiment.yaml"
    source = project / "src" / "experiment.py"

    manifest.parent.mkdir(parents=True, exist_ok=True)
    source.parent.mkdir(parents=True, exist_ok=True)

    manifest.write_text(
        "apiVersion: quantumd.ai/v0.1\n",
        encoding="utf-8",
    )
    source.write_text(
        "print('governed')\n",
        encoding="utf-8",
    )

    run_id = "20260726T001158.548294Z-test"
    execution_id = "QEXEC-20260726-test"
    key_version = "projects/test/keyVersions/1"

    verification = {
        "schema_version": "quantumd.ai/evidence/v0.1",
        "run_id": run_id,
        "final_decision": "VERIFIED_EDUCATIONAL_ONLY",
        "finalized_at": "2026-07-26T00:12:00+00:00",
        "hashes": {
            "manifest_sha256": chain._sha256_file(
                manifest
            ),
            "source": {
                "path": "src/experiment.py",
                "sha256": chain._sha256_file(source),
            },
        },
        "integrity": {
            "canonical_payload_sha256": "a" * 64,
            "key_version": key_version,
        },
    }

    _write_json(
        project / "evidence" / "runs" / f"{run_id}.json",
        verification,
    )

    execution_dir = (
        project
        / "evidence"
        / "executions"
        / execution_id
    )

    result_raw = _write_json(
        execution_dir / "results.json",
        {
            "00": 4,
            "11": 4,
        },
    )

    receipt = {
        "schema_version": "quantumd.ai/execution/v0.1",
        "execution_id": execution_id,
        "authorization": {
            "signature_verified": True,
            "verification_payload_sha256": "a" * 64,
            "verification_run_id": run_id,
        },
        "integrity": {
            "canonical_payload_sha256": "b" * 64,
            "key_version": key_version,
        },
        "results": {
            "artifact": "results.json",
            "sha256": _sha256(result_raw),
        },
        "shots": 8,
        "status": "EXECUTION_COMPLETED",
        "target": {
            "backend": "aer-simulator",
            "provider": "local",
        },
        "timestamp": "2026-07-26T00:13:20+00:00",
        "workload": {
            "executed_circuit": {
                "format": "QPY",
                "sha256": "c" * 64,
            },
            "logical_circuit": {
                "format": "QPY",
                "sha256": "d" * 64,
            },
            "manifest_sha256": chain._sha256_file(
                manifest
            ),
            "source_sha256": chain._sha256_file(source),
        },
        "workload_executed": True,
    }

    _write_json(
        execution_dir / "receipt.json",
        receipt,
    )

    monkeypatch.setattr(
        chain,
        "_find_local_public_key",
        lambda project, verification, receipt: (
            project / "evidence" / "public-key.pem",
            object(),
        ),
    )
    monkeypatch.setattr(
        chain,
        "_verify_local_record",
        lambda *args, **kwargs: None,
    )

    context = chain._load_chain(
        project,
        None,
        None,
        True,
    )

    return context, source


def test_local_chain_verifies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _ = _build_local_chain(
        tmp_path,
        monkeypatch,
    )

    checks = chain._verify_chain(context)

    assert context["chain_type"] == "local"
    assert (
        "Result artifact SHA-256 binding"
        in checks
    )


def test_local_chain_denies_source_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, source = _build_local_chain(
        tmp_path,
        monkeypatch,
    )

    source.write_text(
        "print('tampered')\n",
        encoding="utf-8",
    )

    with pytest.raises(
        chain.ChainVerificationError
    ):
        chain._verify_chain(context)



def test_local_record_uses_empty_integrity_canonicalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unsigned_payload = {
        "run_id": "local-canonicalization-test",
        "integrity": {},
    }

    declared_hash = chain._sha256_bytes(
        chain._canonical(unsigned_payload)
    )

    record = {
        "run_id": "local-canonicalization-test",
        "integrity": {
            "canonical_payload_sha256": declared_hash,
        },
    }

    monkeypatch.setattr(
        chain,
        "_decode_signature",
        lambda *args, **kwargs: b"signature",
    )

    monkeypatch.setattr(
        chain,
        "_verify_digest_signature",
        lambda *args, **kwargs: None,
    )

    result = chain._verify_local_record(
        object(),
        record,
        "LOCAL",
    )

    assert result == b"signature"
