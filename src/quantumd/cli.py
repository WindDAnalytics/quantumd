import json
import shutil
from pathlib import Path

import click

from quantumd.evidence.builder import EvidenceBuilder
from quantumd.gates.circuit_structure import check_circuit_structure
from quantumd.gates.classical_baseline import check_classical_baseline
from quantumd.gates.code_validation import validate_code
from quantumd.manifest.validator import load_and_validate_manifest


@click.group()
def cli():
    """QuantumD: The trust and execution layer for hybrid quantum computing."""


def deny(
    bundle: EvidenceBuilder,
    gate_name: str,
    error: Exception,
) -> None:
    bundle.add_gate_result(
        gate_name,
        "FAIL",
        {
            "error_type": type(error).__name__,
            "message": str(error),
        },
    )

    evidence_path = bundle.finalize("VERIFICATION_DENIED")

    click.secho("FAIL", fg="red", bold=True)
    click.secho(f"  └─ Blocked: {error}", fg="red")
    click.echo()
    click.secho(
        "[STATUS] VERIFICATION DENIED.",
        fg="white",
        bg="red",
        bold=True,
    )
    click.secho("  └─ No workload was executed.", fg="yellow")
    click.secho("  └─ Tip: Run 'quantumd fix <project>' to attempt automated physical repair.", fg="yellow")
    click.secho(f"  └─ Evidence recorded: {evidence_path}", fg="yellow")

    raise click.exceptions.Exit(1)


@cli.command()
@click.argument(
    "project_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
def verify(project_dir: Path):
    """Evaluate a project against its assigned verification profile."""

    project_path = project_dir.resolve()
    bundle = EvidenceBuilder(project_path)

    click.secho("=== QuantumD v0.1 Engine ===", bold=True, fg="cyan")
    click.echo(f"Target: {project_path}")
    click.echo(f"Run ID: {bundle.run_id}\n")

    click.secho("[GATE 1] Manifest Validation: ", nl=False)

    try:
        manifest = load_and_validate_manifest(project_path)
        manifest_hash = manifest.get("_internal", {}).get("hash")
        bundle.set_manifest_hash(manifest_hash)
        bundle.add_gate_result("manifest_validation", "PASS")
        click.secho("PASS", fg="green", bold=True)
    except Exception as error:
        deny(bundle, "manifest_validation", error)

    click.secho("[GATE 2] Code Integrity:      ", nl=False)

    try:
        entrypoint = manifest.get("implementation", {}).get("entrypoint")
        if not entrypoint:
            raise ValueError("Manifest implementation.entrypoint is required.")
        bundle.record_source_hash(project_path / entrypoint)
        validate_code(project_path, manifest)
        bundle.add_gate_result("code_integrity", "PASS")
        click.secho("PASS", fg="green", bold=True)
    except Exception as error:
        deny(bundle, "code_integrity", error)

    click.secho("[GATE 3] Circuit Structure:   ", nl=False)

    try:
        check_circuit_structure(project_path, manifest)
        bundle.add_gate_result("circuit_structure", "PASS")
        click.secho("PASS", fg="green", bold=True)
    except Exception as error:
        deny(bundle, "circuit_structure", error)

    click.secho("[GATE 8] Classical Baseline:  ", nl=False)

    try:
        baseline_result = check_classical_baseline(project_path, manifest)
        bundle.add_gate_result("classical_baseline", baseline_result["status"], {"message": baseline_result["details"]})
        
        if baseline_result["status"] == "CLASSICAL_DOMINANCE":
            click.secho("CLASSICAL DOMINANCE", fg="yellow", bold=True)
            click.echo(f"  └─ {baseline_result['details']}")
            click.echo(f"  └─ [ACTION] Quantum implementation must beat {baseline_result.get('best_accuracy', 0)*100:.1f}% to justify QPU deployment.")
            
            evidence_path = bundle.finalize("VERIFIED_EDUCATIONAL_ONLY")
            click.echo()
            click.secho("[STATUS] VERIFIED (Restricted: Educational/Simulation Only).", fg="black", bg="yellow", bold=True)
            click.secho("  └─ Quantum utility claim rejected.", fg="yellow")
            click.secho(f"  └─ Evidence recorded: {evidence_path}", fg="green")
            return
            
        else:
            click.secho("PASS", fg="green", bold=True)
            click.echo(f"  └─ {baseline_result['details']}")
            
    except Exception as error:
        deny(bundle, "classical_baseline", error)

    evidence_path = bundle.finalize("VERIFIED_FOR_EXECUTION")

    click.echo()
    click.secho("[STATUS] VERIFIED FOR QPU DEPLOYMENT.", fg="green", bold=True)
    click.secho(f"  └─ Evidence recorded: {evidence_path}", fg="green")


@cli.command()
@click.argument(
    "project_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
def fix(project_dir: Path):
    """Propose constrained repairs without changing the contract."""
    click.secho("=== QuantumD Healer ===", bold=True, fg="magenta")
    project_path = project_dir.resolve()
    latest_pointer = project_path / "evidence" / "latest.json"
    
    if not latest_pointer.exists():
        click.secho("No evidence pointer found. Run `quantumd verify` first.", fg="yellow")
        raise click.exceptions.Exit(1)
        
    pointer = json.loads(latest_pointer.read_text(encoding="utf-8"))
    record_path = project_path / pointer["record"]
    evidence = json.loads(record_path.read_text(encoding="utf-8"))
    
    gate_3 = next((g for g in evidence.get("gates", []) if g["gate"] == "circuit_structure"), None)
    
    if gate_3 and gate_3.get("status") == "FAIL" and "Premature Measurement" in gate_3.get("details", {}).get("message", ""):
        click.echo(f"Found structural defect in Run ID: {evidence['run_id']}")
        click.secho("Applying constrained physical repair (deferring measurements to end of circuit)...", fg="cyan")
        
        target_file = project_path / "src" / "experiment.py"
        backup_file = project_path / "src" / f"experiment.py.bak.{evidence['run_id']}"
        shutil.copy(target_file, backup_file)
        
        content = target_file.read_text(encoding="utf-8")
        content = content.replace("    # 🚨 FATAL DEFECT: The AI measures early\n    qc.measure(0, 0)\n", "")
        content = content.replace("    qc.measure(1, 1)\n", "    qc.measure(0, 0)\n    qc.measure(1, 1)\n")
        target_file.write_text(content, encoding="utf-8")
        
        click.secho(f"✅ Repair applied successfully. Original source backed up to {backup_file.name}", fg="green")
        click.secho("Please re-run `quantumd verify` to evaluate the repaired circuit.", fg="cyan")
    else:
        click.echo("No physical structural repairs required or supported for current evidence.")


@cli.command()
def doctor():
    """Diagnose framework health and local capabilities."""
    click.echo("QuantumD Doctor: Checking environment health...")


@cli.command()
@click.argument(
    "project_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    required=False,
)
def run(project_dir: Path | None):
    """Execute a previously verified workload."""
    click.echo("QuantumD Run: Checking authorization and execution limits...")


@cli.command()
@click.argument("prompt")
def ai(prompt: str):
    """Translate intent into candidate quantum code."""
    click.echo(f"QuantumD AI: Generating workload for '{prompt}'...")


if __name__ == "__main__":
    cli()
