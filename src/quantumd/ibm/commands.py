from __future__ import annotations

from pathlib import Path

import click

from quantumd.ibm.planning import create_ibm_plan


def register_ibm_commands(cli) -> None:
    @cli.command("plan")
    @click.argument(
        "project",
        type=click.Path(
            exists=True,
            file_okay=False,
            path_type=Path,
        ),
    )
    @click.option(
        "--target",
        required=True,
        help="IBM target in the form ibm:<backend-name>.",
    )
    @click.option(
        "--shots",
        default=128,
        show_default=True,
        type=click.IntRange(min=1),
    )
    @click.option(
        "--seed",
        default=1729,
        show_default=True,
        type=int,
    )
    @click.option(
        "--optimization-level",
        default=1,
        show_default=True,
        type=click.IntRange(min=0, max=3),
    )
    def plan_command(
        project: Path,
        target: str,
        shots: int,
        seed: int,
        optimization_level: int,
    ) -> None:
        """
        Create a signed IBM execution plan without submitting hardware.
        """
        project = project.resolve()

        click.echo(
            "=== QuantumD IBM Governed Execution Plan ==="
        )
        click.echo(f"Project:              {project}")
        click.echo(f"Target:               {target}")
        click.echo(f"Shots:                {shots}")
        click.echo()

        try:
            plan_path = create_ibm_plan(
                project_dir=project,
                target=target,
                shots=shots,
                seed=seed,
                optimization_level=optimization_level,
            )
        except Exception as exc:
            raise click.ClickException(
                f"{type(exc).__name__}: {exc}"
            ) from exc

        click.secho(
            "[PLAN] IBM discovery and ISA transpilation... PASS",
            fg="green",
            bold=True,
        )
        click.echo()
        click.echo("Signed execution plan:")
        click.echo(f"  {plan_path.resolve().relative_to(project.resolve())}")
        click.echo()
        click.secho(
            "[STATUS] PLANNED — NO HARDWARE SUBMITTED",
            fg="cyan",
            bold=True,
        )
