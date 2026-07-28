from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from quantumd import chain
from quantumd.cli import cli
from quantumd.evidence import builder as builder_module
from quantumd.evidence.builder import EvidenceBuilder
from quantumd.execution.authorization import (
    AuthorizationEngine,
)
from quantumd.local_trust import (
    PROVIDER,
    SIGNATURE_STATUS,
    initialize as initialize_local_trust,
)
from quantumd.project_init import initialize_project


def _latest_evidence(project: Path) -> dict:
    pointer = json.loads(
        (
            project
            / "evidence"
            / "latest.json"
        ).read_text(encoding="utf-8")
    )
    return json.loads(
        (
            project
            / pointer["record"]
        ).read_text(encoding="utf-8")
    )


def _latest_receipt(project: Path) -> dict:
    paths = list(
        (
            project
            / "evidence"
            / "executions"
        ).glob("QEXEC-*/receipt.json")
    )
    assert paths
    path = max(
        paths,
        key=lambda value: value.stat().st_mtime_ns,
    )
    return json.loads(
        path.read_text(encoding="utf-8")
    )


def test_local_trust_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(
        "QUANTUMD_KMS_KEY_VERSION",
        raising=False,
    )

    project = tmp_path / "quickstart"
    initialize_project(project)
    initialize_local_trust(project)

    runner = CliRunner()

    verification = runner.invoke(
        cli,
        ["verify", str(project)],
    )
    assert verification.exit_code == 0, verification.output

    evidence = _latest_evidence(project)
    integrity = evidence["integrity"]

    assert integrity["signed"] is True
    assert integrity["provider"] == PROVIDER
    assert (
        integrity["signature_status"]
        == SIGNATURE_STATUS
    )
    assert (
        integrity["hardware_authorization"]
        == "PROHIBITED"
    )

    execution = runner.invoke(
        cli,
        [
            "run",
            str(project),
            "--target",
            "aer-simulator",
            "--shots",
            "8",
            "--latest",
        ],
    )
    assert execution.exit_code == 0, execution.output
    assert (
        "LOCAL DEVELOPMENT ATTESTATION"
        in execution.output
    )
    assert (
        "Hardware authorization: PROHIBITED"
        in execution.output
    )

    receipt = _latest_receipt(project)
    receipt_integrity = receipt["integrity"]

    assert receipt["status"] == "EXECUTION_COMPLETED"
    assert receipt_integrity["signed"] is True
    assert receipt_integrity["provider"] == PROVIDER
    assert (
        receipt_integrity["key_version"]
        == integrity["key_version"]
    )

    offline = runner.invoke(
        cli,
        [
            "verify-chain",
            str(project),
            "--latest",
        ],
    )
    assert offline.exit_code == 0, offline.output
    assert (
        "COMPLETE EVIDENCE CHAIN VERIFIED"
        in offline.output
    )


def test_local_trust_denies_ibm_before_kms(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(
        "QUANTUMD_KMS_KEY_VERSION",
        raising=False,
    )

    project = tmp_path / "hardware-denied"
    initialize_project(project)
    initialize_local_trust(project)

    result = CliRunner().invoke(
        cli,
        ["verify", str(project)],
    )
    assert result.exit_code == 0, result.output

    evidence = _latest_evidence(project)

    def forbidden_kms_client():
        raise AssertionError(
            "KMS must not be contacted for local hardware denial."
        )

    monkeypatch.setattr(
        "quantumd.execution.authorization."
        "kms.KeyManagementServiceClient",
        forbidden_kms_client,
    )

    with pytest.raises(
        PermissionError,
        match="LOCAL_DEVELOPMENT_TRUST_SCOPE_VIOLATION",
    ):
        AuthorizationEngine.authorize(
            project,
            evidence["run_id"],
            "ibm:ibm_fez",
        )


def test_local_signature_cannot_sign_remote_node(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(
        "QUANTUMD_KMS_KEY_VERSION",
        raising=False,
    )

    project = tmp_path / "remote-node-denied"
    (project / "evidence").mkdir(parents=True)
    initialize_local_trust(project)

    builder = EvidenceBuilder(project)
    path = builder.finalize(
        "VERIFIED_FOR_LOCAL_SIMULATION"
    )
    record = json.loads(
        path.read_text(encoding="utf-8")
    )

    assert (
        record["integrity"]["provider"]
        == "quantumd-local-development"
    )
    assert (
        record["integrity"]["signature_status"]
        == "LOCAL_DEVELOPMENT_SIGNED"
    )

    with pytest.raises(
        chain.ChainVerificationError,
        match="cannot authorize remote governance node",
    ):
        chain._decode_signature(
            record,
            "QPLAN",
        )


def test_kms_precedes_initialized_local_trust(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "kms-precedence"
    (project / "evidence").mkdir(parents=True)
    initialize_local_trust(project)

    monkeypatch.setenv(
        "QUANTUMD_KMS_KEY_VERSION",
        "projects/test/keyVersions/1",
    )

    calls: list[tuple[str, str]] = []

    def fake_kms_sign(
        payload_hash_hex: str,
        key_version_name: str,
        evidence_root: Path | None = None,
    ) -> dict:
        calls.append(
            (
                payload_hash_hex,
                key_version_name,
            )
        )
        return {
            "algorithm": "EC_SIGN_P256_SHA256",
            "key_version": key_version_name,
            "provider": "gcp-cloud-kms",
            "signature_status": "KMS_SIGNED",
            "signed": True,
            "value_base64": "AA==",
        }

    monkeypatch.setattr(
        builder_module,
        "sign_payload_with_kms",
        fake_kms_sign,
    )

    path = EvidenceBuilder(project).finalize(
        "VERIFIED_FOR_EXECUTION"
    )
    record = json.loads(
        path.read_text(encoding="utf-8")
    )

    assert calls
    assert (
        record["integrity"]["provider"]
        == "gcp-cloud-kms"
    )
    assert (
        record["integrity"]["signature_status"]
        == "KMS_SIGNED"
    )


def test_initialized_project_ignores_local_private_identity(
    tmp_path: Path,
) -> None:
    project = tmp_path / "gitignore"
    initialize_project(project)

    gitignore = (
        project / ".gitignore"
    ).read_text(encoding="utf-8")

    assert ".quantumd/local-trust/" in gitignore
