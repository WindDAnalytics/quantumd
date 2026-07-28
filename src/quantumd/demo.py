from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import click

from quantumd.project_init import initialize_project


class DemoError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    returncode: int
    output: str


def _quantumd_command() -> list[str]:
    executable = shutil.which("quantumd")
    if executable:
        return [executable]
    return [
        sys.executable,
        "-c",
        "from quantumd.cli import cli; cli()",
    ]


def _run_quantumd(
    arguments: Sequence[str],
    *,
    cwd: Path,
) -> CommandResult:
    command = [*_quantumd_command(), *arguments]
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=os.environ.copy(),
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
        raise DemoError(
            f"{label} failed with exit code "
            f"{result.returncode}.\n{result.output}"
        )
    if required_text and required_text not in result.output:
        raise DemoError(
            f"{label} did not emit expected proof: "
            f"{required_text!r}."
        )


def _latest_receipt(project: Path) -> Path:
    receipts = list(
        (project / "evidence" / "executions").glob(
            "QEXEC-*/receipt.json"
        )
    )
    if not receipts:
        raise DemoError("No execution receipt was generated.")
    return max(receipts, key=lambda path: path.stat().st_mtime_ns)


def _validate_artifacts(project: Path, receipt_path: Path) -> Path:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    integrity = receipt.get("integrity", {})
    if (
        integrity.get("signed") is not True
        or integrity.get("signature_status") != "KMS_SIGNED"
    ):
        raise DemoError("Execution receipt is not KMS-attested.")

    target = receipt.get("target", {})
    if (
        target.get("provider") != "local"
        or target.get("backend") != "aer-simulator"
    ):
        raise DemoError("Demo escaped the local Aer target.")

    if not (project / "evidence" / "public-key.pem").is_file():
        raise DemoError("Verified public key was not auto-cached.")

    artifact = receipt.get("results", {}).get("artifact")
    if (
        not isinstance(artifact, str)
        or not artifact
        or Path(artifact).name != artifact
    ):
        raise DemoError(f"Invalid result artifact: {artifact!r}")

    result_path = receipt_path.parent / artifact
    if not result_path.is_file():
        raise DemoError(f"Result artifact missing: {result_path}")
    return result_path


def _tamper_result(result_path: Path) -> bytes:
    original = result_path.read_bytes()
    counts = json.loads(original.decode("utf-8"))
    if not isinstance(counts, dict) or not counts:
        raise DemoError("Result artifact has no count mapping.")
    first_key = next(iter(counts))
    value = counts[first_key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise DemoError("Result artifact has a non-integer count.")
    counts[first_key] = value + 1
    result_path.write_text(
        json.dumps(counts, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return original


def _restore_result(result_path: Path, original: bytes) -> None:
    result_path.write_bytes(original)


def _step(number: int, total: int, label: str, status: str) -> None:
    dots = "." * max(1, 44 - len(label))
    click.echo(f"[{number}/{total}] {label}{dots} {status}")


@click.command("demo")
@click.option(
    "--keep",
    is_flag=True,
    help="Keep the generated demo project for inspection.",
)
@click.option(
    "--skip-tamper",
    is_flag=True,
    help="Skip the adversarial result-tampering proof.",
)
@click.option(
    "--shots",
    type=click.IntRange(min=1, max=20000),
    default=256,
    show_default=True,
    help="Aer simulator shots used by the demonstration.",
)
def demo_command(keep: bool, skip_tamper: bool, shots: int) -> None:
    """Run the complete governed simulator demonstration."""
    project = Path(
        tempfile.mkdtemp(prefix="quantumd-governed-demo-")
    ).resolve()
    total = 5 if skip_tamper else 7
    completed = False

    click.echo("=== QuantumD Governed Demonstration ===")
    click.echo(f"Project: {project}")
    click.echo("Target:  aer-simulator")
    click.echo(f"Shots:   {shots}")
    click.echo("Hardware submission: prohibited\n")

    try:
        initialize_project(
            project,
            project_name="QuantumD Governed Demo",
        )
        _step(1, total, "Project initialization", "PASS")

        verification = _run_quantumd(["verify", "."], cwd=project)
        _require_success(
            verification,
            "Verification and policy gates",
        )
        _step(2, total, "Verification and policy gates", "PASS")

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
            "Governed Aer execution",
            "EXECUTION COMPLETED AND ATTESTED",
        )
        _step(3, total, "Governed Aer execution", "PASS")

        receipt_path = _latest_receipt(project)
        result_path = _validate_artifacts(project, receipt_path)
        _step(4, total, "Signed evidence and key cache", "PASS")

        first_chain = _run_quantumd(
            ["verify-chain", ".", "--latest"],
            cwd=project,
        )
        _require_success(
            first_chain,
            "Offline chain verification",
            "COMPLETE EVIDENCE CHAIN VERIFIED",
        )
        for proof in (
            "IBM contacted:   False",
            "KMS contacted:   False",
            "Hardware action: None",
        ):
            if proof not in first_chain.output:
                raise DemoError(
                    f"Offline verifier did not confirm: {proof}"
                )
        _step(5, total, "Offline chain verification", "PASS")

        if not skip_tamper:
            original = _tamper_result(result_path)
            try:
                denied = _run_quantumd(
                    ["verify-chain", ".", "--latest"],
                    cwd=project,
                )
                if denied.returncode == 0:
                    raise DemoError(
                        "Tampered result was unexpectedly accepted."
                    )
                if "CHAIN VERIFICATION DENIED" not in denied.output:
                    raise DemoError(
                        "Tampering did not emit deterministic denial."
                    )
                _step(
                    6,
                    total,
                    "Adversarial result tampering",
                    "DENIED",
                )
            finally:
                _restore_result(result_path, original)

            restored = _run_quantumd(
                ["verify-chain", ".", "--latest"],
                cwd=project,
            )
            _require_success(
                restored,
                "Authentic evidence restoration",
                "COMPLETE EVIDENCE CHAIN VERIFIED",
            )
            _step(
                7,
                total,
                "Authentic evidence restoration",
                "PASS",
            )

        completed = True
        click.echo()
        click.secho(
            "[STATUS] QUANTUMD GOVERNED DEMONSTRATION COMPLETE",
            fg="green",
            bold=True,
        )
        click.echo("IBM contacted:   False")
        click.echo("KMS contacted by offline verification: False")
        click.echo("Hardware action: None")
        if keep:
            click.echo(f"Demo retained:   {project}")

    except Exception as exc:
        click.echo()
        click.secho(
            "[STATUS] QUANTUMD GOVERNED DEMONSTRATION FAILED",
            fg="red",
            bold=True,
        )
        click.echo(f"  └─ {type(exc).__name__}: {exc}")
        raise click.exceptions.Exit(1) from exc

    finally:
        if not keep:
            shutil.rmtree(project, ignore_errors=True)
            if completed:
                click.echo("Temporary project cleaned: True")
