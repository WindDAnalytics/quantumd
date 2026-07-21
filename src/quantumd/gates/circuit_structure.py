import sys
import importlib.util
from pathlib import Path

def check_circuit_structure(project_dir: Path, manifest: dict):
    entrypoint = manifest.get("implementation", {}).get("entrypoint")
    target_file = project_dir / entrypoint
        
    sys.path.insert(0, str(project_dir))
    spec = importlib.util.spec_from_file_location("user_experiment", target_file)
    user_module = importlib.util.module_from_spec(spec)
    sys.modules["user_experiment"] = user_module
    spec.loader.exec_module(user_module)
    sys.path.pop(0)
    
    func = None
    for name in ["get_circuit", "build_circuit", "create_circuit", "experiment"]:
        if hasattr(user_module, name):
            func = getattr(user_module, name)
            break
            
    if not func:
        raise AttributeError("Experiment must define a circuit builder function (e.g., 'get_circuit').")
        
    try:
        qc = func()
    except Exception as e:
        raise RuntimeError(f"Circuit generation failed: {str(e)}")
    
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
