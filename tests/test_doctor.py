from __future__ import annotations

from click.testing import CliRunner

from quantumd.cli import cli
from quantumd.local_trust import (
    initialize as initialize_local_trust,
)
from quantumd.project_init import initialize_project


def test_doctor_reports_local_development(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.delenv(
        "QUANTUMD_KMS_KEY_VERSION",
        raising=False,
    )

    project = tmp_path / "local"
    initialize_project(project)
    initialize_local_trust(project)

    result = CliRunner().invoke(
        cli,
        ["doctor", str(project)],
    )

    assert result.exit_code == 0, result.output
    assert (
        "Active trust mode:      LOCAL_DEVELOPMENT"
        in result.output
    )
    assert (
        "Hardware authorization: PROHIBITED"
        in result.output
    )
    assert (
        "QUANTUMD ENVIRONMENT READY"
        in result.output
    )


def test_doctor_reports_kms_precedence(
    tmp_path,
    monkeypatch,
) -> None:
    project = tmp_path / "hybrid"
    initialize_project(project)
    initialize_local_trust(project)

    monkeypatch.setenv(
        "QUANTUMD_KMS_KEY_VERSION",
        "projects/test/keyVersions/1",
    )

    result = CliRunner().invoke(
        cli,
        ["doctor", str(project)],
    )

    assert result.exit_code == 0, result.output
    assert (
        "Active trust mode:      KMS_GOVERNED"
        in result.output
    )
    assert (
        "KMS_GOVERNED over LOCAL_DEVELOPMENT"
        in result.output
    )


def test_doctor_reports_unconfigured(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.delenv(
        "QUANTUMD_KMS_KEY_VERSION",
        raising=False,
    )

    result = CliRunner().invoke(
        cli,
        ["doctor", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    assert (
        "Active trust mode:      UNCONFIGURED"
        in result.output
    )
    assert (
        "TRUST NOT CONFIGURED"
        in result.output
    )
