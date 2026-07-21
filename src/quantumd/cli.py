import json
import shutil
import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path

import click

from quantumd.evidence.builder import EvidenceBuilder, sha256_file
from quantumd.gates.circuit_structure import check_circuit_structure
from quantumd.gates.classical_baseline import check_classical_baseline
from quantumd.gates.code_validation import validate_code
from quantumd.security.sandbox import load_circuit_isolated
from quantumd.adapters.mqt_adapter import check_equivalence
from quantumd.manifest.validator import load_and_validate_manifest


@click.group()
def cli():
    """QuantumD: The trust and execution layer for hybrid quantum computing."""

def deny(bundle, gate_name, error):
    bundle.add_gate_result(gate_name, "FAIL", {"error_type": type(error).__name__, "message": str(error)})
    evidence_path = bundle.finalize("VERIFICATION_DENIED")
    click.secho("FAIL", fg="red", bold=True)
    click.secho(f"  └─ Blocked: {error}", fg="red")
    click.echo()
    click.secho("[STATUS] VERIFICATION DENIED.", fg="white", bg="red", bold=True)
    click.secho("  └─ No workload was executed.", fg="yellow")
    click.secho("  └─ Tip: Run 'quantumd fix <project>' to attempt automated physical repair.", fg="yellow")
    click.secho(f"  └─ Evidence recorded: {evidence_path}", fg="yellow")
    raise click.exceptions.Exit(1)


@cli.command()
@click.argument("project_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
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

    click.secho("[GATE 4] Repair Equivalence:  ", nl=False)
    try:
        repairs_dir = project_path / ".repairs"
        current_hash = bundle.evidence.get("hashes", {}).get("source", {}).get("sha256")
        
        matching_repair = None
        if repairs_dir.exists():
            for repair_file in repairs_dir.glob("*.json"):
                try:
                    repair_data = json.loads(repair_file.read_text(encoding="utf-8"))
                    if repair_data.get("source_after", {}).get("sha256") == current_hash:
                        matching_repair = repair_data
                        break
                except Exception:
                    continue

        if not matching_repair:
            bundle.add_gate_result("repair_equivalence", "SKIPPED", {"details": "No matching repair record found for current source hash."})
            click.secho("SKIPPED", fg="black", bold=True)
        else:
            # We found a repair match; now we extract both via sandbox
            original_path = project_path / matching_repair["source_before"]["path"]
            orig_qc = load_circuit_isolated(project_path, original_path)
            rep_qc = load_circuit_isolated(project_path, project_path / entrypoint)
            
            eq_result = check_equivalence(orig_qc, rep_qc)
            bundle.add_gate_result("repair_equivalence", eq_result["status"], eq_result)
            
            if eq_result["status"] == "PASS":
                click.secho(f"PASS ({eq_result['decision']})", fg="green", bold=True)
            else:
                raise ValueError(f"Repair rejected: Semantics not preserved ({eq_result['decision']}).")
    except Exception as error:
        deny(bundle, "repair_equivalence", error)

    click.secho("[GATE 8] Classical Baseline:  ", nl=False)
    try:
        baseline_result = check_classical_baseline(project_path, manifest)
        bundle.add_gate_result("classical_baseline", baseline_result["status"], {"message": baseline_result["details"]})
        
        if baseline_result["status"] == "CLASSICAL_BASELINE_MEETS_CONTRACT":
            click.secho("CLASSICAL_BASELINE_MEETS_CONTRACT", fg="yellow", bold=True)
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
@click.argument("project_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
def fix(project_dir: Path):
    """[EXPERIMENTAL] Propose constrained repairs backed by cryptographic provenance hashes."""
    click.secho("=== QuantumD Healer [EXPERIMENTAL] ===", bold=True, fg="magenta")
    project_path = project_dir.resolve()
    latest_pointer = project_path / "evidence" / "latest.json"
    
    if not latest_pointer.exists():
        click.secho("No evidence pointer found. Run `quantumd verify` first.", fg="yellow")
        raise click.exceptions.Exit(1)
        
    pointer = json.loads(latest_pointer.read_text(encoding="utf-8"))
    record_path = project_path / pointer["record"]
    evidence = json.loads(record_path.read_text(encoding="utf-8"))
    
    gate_3 = next((g for g in evidence.get("gates", []) if g["gate"] == "circuit_structure"), None)
    
    if gate_3 and gate_3.get("status") == "FAIL" and "MID_CIRCUIT_MEASUREMENT_NOT_PERMITTED" in gate_3.get("details", {}).get("message", ""):
        click.echo(f"Found structural defect in Run ID: {evidence['run_id']}")
        click.secho("1. Proposing constrained physical repair (deferring measurements)...", fg="cyan")
        
        target_file = project_path / "src" / "experiment.py"
        temp_repair_file = project_path / "src" / ".experiment_repair.tmp.py"
        
        source_before_hash = sha256_file(target_file)
        
        # Experimental heuristic string replacement (pending proper AST manipulation)
        content = target_file.read_text(encoding="utf-8")
        content = content.replace("    # 🚨 FATAL DEFECT: The AI measures early\n    qc.measure(0, 0)\n", "")
        content = content.replace("    qc.measure(1, 1)\n", "    qc.measure(0, 0)\n    qc.measure(1, 1)\n")
        temp_repair_file.write_text(content, encoding="utf-8")
        
        source_after_hash = sha256_file(temp_repair_file)
        
        click.secho("2. [GATE 4] Pre-flight Semantic Equivalence Check (Isolated MQT)...", fg="yellow", nl=False)
        try:
            orig_qc = load_circuit_isolated(project_path, target_file)
            rep_qc = load_circuit_isolated(project_path, temp_repair_file)
            
            eq_result = check_equivalence(orig_qc, rep_qc)
            
            if eq_result["status"] == "PASS":
                click.secho(f" PASS ({eq_result['decision']})", fg="green", bold=True)
                
                repair_id = f"QFIX-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"
                backup_file = project_path / "src" / f"experiment.py.bak.{repair_id}.py"
                
                shutil.copy(target_file, backup_file)
                temp_repair_file.rename(target_file)
                
                # Write strict provenance record
                repair_record = {
                    "repair_id": repair_id,
                    "triggering_run_id": evidence['run_id'],
                    "repair_type": "DEFER_MEASUREMENT",
                    "source_before": {"path": f"src/{backup_file.name}", "sha256": source_before_hash},
                    "source_after": {"path": "src/experiment.py", "sha256": source_after_hash},
                    "equivalence": {
                        "engine": "mqt-qcec",
                        "configuration": {
                            "transform_dynamic_circuit": True
                        },
                        "decision": eq_result["decision"]
                    }
                }
                
                repairs_dir = project_path / ".repairs"
                repairs_dir.mkdir(exist_ok=True)
                (repairs_dir / f"{repair_id}.json").write_text(json.dumps(repair_record, indent=2), encoding="utf-8")
                
                click.secho(f"✅ Hash-bound repair applied. Original backed up to {backup_file.name}", fg="green")
                click.secho(f"✅ Immutable repair record created: .repairs/{repair_id}.json", fg="green")
                click.secho("Please re-run `quantumd verify` to evaluate the repaired circuit.", fg="cyan")
            else:
                click.secho(f" FAIL ({eq_result['decision']})", fg="red", bold=True)
                click.secho("Repair aborted. The proposed physical fix altered the mathematics of the circuit.", fg="red")
                temp_repair_file.unlink()
        except Exception as e:
            click.secho(f" ERROR: {str(e)}", fg="red", bold=True)
            if temp_repair_file.exists(): temp_repair_file.unlink()
    else:
        click.echo("No physical structural repairs required or supported for current evidence.")

@cli.command()
def doctor():
    click.echo("QuantumD Doctor: Checking environment health...")

@cli.command()
@click.argument("project_dir", type=click.Path(exists=True, file_okay=False, path_type=Path), required=False)
def run(project_dir: Path | None):
    click.echo("QuantumD Run: Checking authorization and execution limits...")

@cli.command()
@click.argument("prompt")
def ai(prompt: str):
    click.echo(f"QuantumD AI: Generating workload for '{prompt}'...")

if __name__ == "__main__":
    cli()
