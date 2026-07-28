from __future__ import annotations

import os
from importlib.metadata import (
    PackageNotFoundError,
    version,
)
from pathlib import Path

import click

from quantumd.local_trust import (
    exists as local_trust_exists,
    inspect as inspect_local_trust,
)


def _package_version() -> str:
    try:
        return version("quantumd")
    except PackageNotFoundError:
        return "source-tree"


def _aer_status() -> tuple[str, str | None]:
    try:
        from qiskit_aer import AerSimulator

        simulator = AerSimulator()
        return "AVAILABLE", type(simulator).__name__
    except Exception as exc:
        return "UNAVAILABLE", str(exc)


@click.command("doctor")
@click.argument(
    "project_dir",
    required=False,
    default=".",
    type=click.Path(
        file_okay=False,
        path_type=Path,
    ),
)
def doctor_command(project_dir: Path) -> None:
    """Report QuantumD trust and simulator readiness."""
    project = project_dir.expanduser().resolve()
    kms_key = os.environ.get(
        "QUANTUMD_KMS_KEY_VERSION"
    )

    manifest_present = (
        project / "experiment.yaml"
    ).is_file()

    local_present = local_trust_exists(project)
    local_valid = False
    local_error: str | None = None
    local_metadata: dict | None = None

    if local_present:
        try:
            local_metadata = inspect_local_trust(
                project
            )
            local_valid = True
        except Exception as exc:
            local_error = (
                f"{type(exc).__name__}: {exc}"
            )

    if kms_key:
        trust_mode = "KMS_GOVERNED"
    elif local_valid:
        trust_mode = "LOCAL_DEVELOPMENT"
    elif local_present:
        trust_mode = "LOCAL_TRUST_INVALID"
    else:
        trust_mode = "UNCONFIGURED"

    aer_status, aer_detail = _aer_status()

    click.echo("=== QuantumD Doctor ===")
    click.echo(
        f"QuantumD version:       {_package_version()}"
    )
    click.echo(f"Project:                {project}")
    click.echo(
        "Project manifest:       "
        f"{'FOUND' if manifest_present else 'NOT_FOUND'}"
    )
    click.echo(
        f"Aer simulator:          {aer_status}"
    )
    click.echo(
        f"Active trust mode:      {trust_mode}"
    )
    click.echo(
        "KMS key configured:     "
        f"{'True' if kms_key else 'False'}"
    )
    click.echo(
        "Local identity present: "
        f"{'True' if local_present else 'False'}"
    )
    click.echo(
        "Local identity valid:   "
        f"{'True' if local_valid else 'False'}"
    )

    if kms_key and local_valid:
        click.echo(
            "Trust precedence:       "
            "KMS_GOVERNED over LOCAL_DEVELOPMENT"
        )

    if local_metadata:
        click.echo(
            "Local trust scope:      "
            f"{local_metadata['trust_scope']}"
        )
        click.echo(
            "Hardware authorization: "
            f"{local_metadata['hardware_authorization']}"
        )

    if local_error:
        click.echo(
            f"Local trust error:      {local_error}"
        )

    if aer_detail:
        click.echo(
            f"Aer backend:            {aer_detail}"
        )

    click.echo()

    if (
        manifest_present
        and aer_status == "AVAILABLE"
        and trust_mode
        in {"KMS_GOVERNED", "LOCAL_DEVELOPMENT"}
    ):
        click.secho(
            "[STATUS] QUANTUMD ENVIRONMENT READY",
            fg="green",
            bold=True,
        )
    elif trust_mode == "UNCONFIGURED":
        click.secho(
            "[STATUS] TRUST NOT CONFIGURED",
            fg="yellow",
            bold=True,
        )
        click.echo(
            "  └─ Run `quantumd quickstart` for "
            "simulator-only local development."
        )
    else:
        click.secho(
            "[STATUS] QUANTUMD ENVIRONMENT NEEDS ATTENTION",
            fg="red",
            bold=True,
        )
