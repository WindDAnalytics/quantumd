from pathlib import Path
from quantumd.security.sandbox import load_circuit_isolated

def check_circuit_structure(project_dir: Path, manifest: dict):
    entrypoint = manifest.get("implementation", {}).get("entrypoint")
    target_file = project_dir / entrypoint
        
    qc = load_circuit_isolated(project_dir, target_file)
    
    measured_qubits = set()
    for instruction in qc.data:
        gate = instruction.operation
        qargs = instruction.qubits
        
        if gate.name == 'measure':
            for q in qargs:
                measured_qubits.add(q)
        elif gate.name not in ['barrier', 'delay']:
            for q in qargs:
                if q in measured_qubits:
                    raise ValueError(
                        "MID_CIRCUIT_MEASUREMENT_NOT_PERMITTED\n\n"
                        "The declared execution target or verification profile does not permit\n"
                        "a measurement before subsequent quantum operations.\n\n"
                        "Execution denied because the workload is incompatible with the\n"
                        "declared target capabilities and experiment contract."
                    )
    return True
