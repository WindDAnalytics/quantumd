import sys
import importlib.util
from pathlib import Path
from qiskit import QuantumCircuit
from quantumd.adapters.mqt_adapter import check_equivalence

def load_circuit_from_file(filepath: Path, module_name: str) -> QuantumCircuit:
    sys.path.insert(0, str(filepath.parent))
    spec = importlib.util.spec_from_file_location(module_name, filepath)
    user_module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = user_module
    spec.loader.exec_module(user_module)
    sys.path.pop(0)
    
    func = None
    for name in ["get_circuit", "build_circuit", "create_circuit", "experiment"]:
        if hasattr(user_module, name):
            func = getattr(user_module, name)
            break
            
    if not func:
        raise AttributeError("Could not extract a circuit building function.")
        
    return func()
