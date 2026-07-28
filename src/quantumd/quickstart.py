from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import click

from quantumd.local_trust import (
    HARDWARE_AUTHORIZATION,
    PROVIDER,
    SIGNATURE_STATUS,
    TRUST_MODE,
    TRUST_SCOPE,
    initialize as initialize_local_trust,
)
from quantumd.project_init import initialize_project


class QuickstartError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    returncode: int
    output: str


def _local_only_environment() -> dict[str, str]:
    environment = os.environ.copy()

    for name in (
        "QUANTUMD_KMS_KEY_VERSION",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_GHA_CREDS_PATH",
        "CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE",
    ):
        environment.pop(name, None)

    return environment


def _run_quantumd(
    arguments: Sequence[str],
    *,
    cwd: Path,
) -> CommandResult:
    command = (
        sys.executable,
        "-m",
        "quantumd.cli",
        *arguments,
    )

    completed = subprocess.run(
        command,
        cwd=cwd,
        env=_local_only_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )

    return CommandResult(
        command=tuple(command),
        returncode=completed.returncode,
        output=completed.stdout or "",
    )


def _require_success(
    result: CommandResult,
    label: str,
    required_text: str | None = None,
) -> None:
    if result.returncode != 0:
        raise QuickstartError(
            f"{label} failed with exit code "
            f"{result.returncode}.\n{result.output}"
        )

    if required_text and required_text not in result.output:
        raise QuickstartError(
            f"{label} did not emit expected proof: "
            f"{required_text!r}.\n{result.output}"
        )


def _read_json(path: Path, label: str) -> dict:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8")
        )
    except FileNotFoundError as exc:
        raise QuickstartError(
            f"{label} not found: {path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise QuickstartError(
            f"{label} is invalid JSON: {path}"
        ) from exc

    if not isinstance(value, dict):
        raise QuickstartError(
            f"{label} is not a JSON object: {path}"
        )

    return value


def _latest_evidence(
    project: Path,
) -> tuple[Path, dict]:
    pointer = _read_json(
        project / "evidence" / "latest.json",
        "Latest evidence pointer",
    )

    record_value = pointer.get("record")

    if (
        not isinstance(record_value, str)
        or not record_value
    ):
        raise QuickstartError(
            "Latest evidence pointer has no record path."
        )

    record_path = (project / record_value).resolve()

    try:
        record_path.relative_to(project)
    except ValueError as exc:
        raise QuickstartError(
            "Latest evidence record escapes the project."
        ) from exc

    return (
        record_path,
        _read_json(record_path, "QVERIFY evidence"),
    )


def _latest_receipt(
    project: Path,
) -> tuple[Path, dict]:
    receipts = list(
        (
            project
            / "evidence"
            / "executions"
        ).glob("QEXEC-*/receipt.json")
    )

    if not receipts:
        raise QuickstartError(
            "No local execution receipt was generated."
        )

    path = max(
        receipts,
        key=lambda value: value.stat().st_mtime_ns,
    )

    return path, _read_json(path, "QEXEC receipt")


def _require_local_integrity(
    record: dict,
    label: str,
) -> dict:
    integrity = record.get("integrity")

    if not isinstance(integrity, dict):
        raise QuickstartError(
            f"{label} integrity metadata is missing."
        )

    required = {
        "hardware_authorization": (
            HARDWARE_AUTHORIZATION
        ),
        "provider": PROVIDER,
        "signature_status": SIGNATURE_STATUS,
        "signed": True,
        "trust_mode": TRUST_MODE,
        "trust_scope": TRUST_SCOPE,
    }

    for field, expected in required.items():
        actual = integrity.get(field)

        if actual != expected:
            raise QuickstartError(
                f"{label} {field} mismatch: "
                f"expected {expected!r}, "
                f"got {actual!r}."
            )

    return integrity


def _validate_local_artifacts(
    project: Path,
) -> dict[str, str]:
    evidence_path, evidence = _latest_evidence(project)
    receipt_path, receipt = _latest_receipt(project)

    evidence_integrity = _require_local_integrity(
        evidence,
        "QVERIFY",
    )
    receipt_integrity = _require_local_integrity(
        receipt,
        "QEXEC",
    )

    if (
        evidence_integrity.get("key_version")
        != receipt_integrity.get("key_version")
    ):
        raise QuickstartError(
            "QVERIFY and QEXEC use different local identities."
        )

    if receipt.get("status") != "EXECUTION_COMPLETED":
        raise QuickstartError(
            "Local execution receipt is not completed."
        )

    target = receipt.get("target")

    if not isinstance(target, dict):
        raise QuickstartError(
            "Local execution target metadata is missing."
        )

    if (
        target.get("provider") != "local"
        or target.get("backend") != "aer-simulator"
    ):
        raise QuickstartError(
            "Quickstart escaped the local Aer boundary."
        )

    if not (
        project / "evidence" / "public-key.pem"
    ).is_file():
        raise QuickstartError(
            "Local verification public key was not cached."
        )

    for forbidden in (
        "plans",
        "approvals",
        "submissions",
    ):
        if (project / "evidence" / forbidden).exists():
            raise QuickstartError(
                f"Unexpected hardware-governance artifact: {forbidden}"
            )

    return {
        "evidence": str(evidence_path),
        "execution": str(receipt_path),
        "key_version": str(
            evidence_integrity["key_version"]
        ),
    }


def _step(
    number: int,
    total: int,
    label: str,
    status: str,
) -> None:
    dots = "." * max(1, 46 - len(label))
    click.echo(
        f"[{number}/{total}] {label}{dots} {status}"
    )


@click.command("quickstart")
@click.argument(
    "path",
    required=False,
    default="quantumd-quickstart",
    type=click.Path(
        file_okay=False,
        path_type=Path,
    ),
)
@click.option(
    "--name",
    "project_name",
    default="QuantumD Local Quickstart",
    show_default=True,
    help="Name written into the generated project.",
)
@click.option(
    "--shots",
    type=click.IntRange(min=1, max=20000),
    default=256,
    show_default=True,
    help="Aer simulator shots.",
)
def quickstart_command(
    path: Path,
    project_name: str,
    shots: int,
) -> None:
    """Create and run a simulator-only governed project."""
    project = path.expanduser().resolve()
    total = 6

    click.echo(
        "=== QuantumD Local Development Quickstart ==="
    )
    click.echo(f"Project:                {project}")
    click.echo(
        "Trust mode:             LOCAL_DEVELOPMENT"
    )
    click.echo(
        "Trust scope:            LOCAL_SIMULATION_ONLY"
    )
    click.echo("Target:                 aer-simulator")
    click.echo(
        "Hardware authorization: PROHIBITED"
    )
    click.echo(f"Shots:                  {shots}\n")

    try:
        if project.exists() and any(project.iterdir()):
            raise QuickstartError(
                "Destination is not empty. Choose a new "
                "path for the governed quickstart."
            )

        initialize_project(
            project,
            project_name=project_name,
        )
        _step(
            1,
            total,
            "Project initialization",
            "PASS",
        )

        trust = initialize_local_trust(project)

        if (
            trust.get("hardware_authorization")
            != HARDWARE_AUTHORIZATION
        ):
            raise QuickstartError(
                "Local identity does not prohibit hardware."
            )

        _step(
            2,
            total,
            "Simulator-only local identity",
            "PASS",
        )

        verification = _run_quantumd(
            ["verify", "."],
            cwd=project,
        )
        _require_success(
            verification,
            "Verification and policy gates",
        )
        _step(
            3,
            total,
            "Verification and policy gates",
            "PASS",
        )

        execution = _run_quantumd(
            [
                "run",
                ".",
                "--target",
                "aer-simulator",
                "--shots",
                str(shots),
                "--latest",
            ],
            cwd=project,
        )
        _require_success(
            execution,
            "Local governed execution",
            "LOCAL DEVELOPMENT ATTESTATION",
        )
        _step(
            4,
            total,
            "Governed Aer execution",
            "PASS",
        )

        artifacts = _validate_local_artifacts(project)
        _step(
            5,
            total,
            "Signed evidence and trust scope",
            "PASS",
        )

        chain = _run_quantumd(
            [
                "verify-chain",
                ".",
                "--latest",
            ],
            cwd=project,
        )
        _require_success(
            chain,
            "Offline evidence-chain verification",
            "COMPLETE EVIDENCE CHAIN VERIFIED",
        )
        _step(
            6,
            total,
            "Offline chain verification",
            "PASS",
        )

        click.echo()
        click.secho(
            "[STATUS] QUANTUMD LOCAL QUICKSTART COMPLETE",
            fg="green",
            bold=True,
        )
        click.echo(
            "Trust mode:             LOCAL_DEVELOPMENT"
        )
        click.echo(
            "Trust scope:            LOCAL_SIMULATION_ONLY"
        )
        click.echo(
            "Hardware authorization: PROHIBITED"
        )
        click.echo(
            "KMS signing used:       False"
        )
        click.echo(
            "IBM contacted:          False"
        )
        click.echo(
            "Hardware action:        None"
        )
        click.echo(
            f"Evidence:               {artifacts['evidence']}"
        )
        click.echo(
            f"Execution receipt:      {artifacts['execution']}"
        )
        click.echo(
            f"Project retained:       {project}"
        )
        click.echo()
        click.echo("Next:")
        click.echo(f"  cd {project}")
        click.echo("  quantumd doctor .")
        click.echo(
            "  quantumd verify-chain . --latest"
        )

    except Exception as exc:
        click.echo()
        click.secho(
            "[STATUS] QUANTUMD LOCAL QUICKSTART FAILED",
            fg="white",
            bg="red",
            bold=True,
        )
        click.echo(
            f"  └─ {type(exc).__name__}: {exc}"
        )
        click.echo(
            f"  └─ Project retained: {project}"
        )
        raise click.exceptions.Exit(1)
