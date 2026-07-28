from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from quantumd.cli import cli


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


def test_quickstart_completes_with_local_trust(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "QUANTUMD_KMS_KEY_VERSION",
        "projects/test/keyVersions/should-not-be-used",
    )

    project = tmp_path / "quickstart"

    result = CliRunner().invoke(
        cli,
        [
            "quickstart",
            str(project),
            "--shots",
            "8",
        ],
    )

    assert result.exit_code == 0, result.output
    assert (
        "QUANTUMD LOCAL QUICKSTART COMPLETE"
        in result.output
    )
    assert (
        "Hardware authorization: PROHIBITED"
        in result.output
    )
    assert (
        "KMS signing used:       False"
        in result.output
    )
    assert (
        "IBM contacted:          False"
        in result.output
    )
    assert (
        "Hardware action:        None"
        in result.output
    )

    evidence = _latest_evidence(project)
    integrity = evidence["integrity"]

    assert (
        integrity["provider"]
        == "quantumd-local-development"
    )
    assert (
        integrity["signature_status"]
        == "LOCAL_DEVELOPMENT_SIGNED"
    )
    assert (
        integrity["hardware_authorization"]
        == "PROHIBITED"
    )


def test_quickstart_refuses_nonempty_destination(
    tmp_path: Path,
) -> None:
    project = tmp_path / "occupied"
    project.mkdir()
    (project / "keep.txt").write_text(
        "do not overwrite\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        ["quickstart", str(project)],
    )

    assert result.exit_code != 0
    assert (
        "Destination is not empty"
        in result.output
    )
    assert (
        project / "keep.txt"
    ).read_text(
        encoding="utf-8"
    ) == "do not overwrite\n"
