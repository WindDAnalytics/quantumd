import os
import subprocess
import sys
import tempfile
from pathlib import Path
from qiskit import qpy, QuantumCircuit

def load_circuit_isolated(project_dir: Path, source_file: Path) -> QuantumCircuit:
    """
    Extracts a circuit by running the untrusted user code in a sanitized,
    time-limited subprocess, serializing it to QPY, and reading it back.
    """
    with tempfile.NamedTemporaryFile(suffix=".qpy", delete=False) as tmp:
        qpy_out = tmp.name
        
    script = f"""
import sys
import importlib.util
from qiskit import qpy

sys.path.insert(0, {str(project_dir.resolve().as_posix())!r})

spec = importlib.util.spec_from_file_location("user_experiment", {str(source_file.resolve().as_posix())!r})
user_module = importlib.util.module_from_spec(spec)
sys.modules["user_experiment"] = user_module
spec.loader.exec_module(user_module)

func = None
for name in ["get_circuit", "build_circuit", "create_circuit", "experiment"]:
    if hasattr(user_module, name):
        func = getattr(user_module, name)
        break

if not func:
    sys.exit(2)

qc = func()
with open({str(qpy_out)!r}, 'wb') as f:
    qpy.dump(qc, f)
"""
    
    env = os.environ.copy()
    # Sanitize environment variables to prevent exfiltration
    for k in list(env.keys()):
        if any(x in k.upper() for x in ["AWS", "GCP", "GOOGLE", "TOKEN", "SECRET", "KEY", "PASSWORD", "KMS"]):
            del env[k]
            
    try:
        res = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=10, env=env)
        
        if res.returncode == 2:
            raise AttributeError(f"Could not extract a circuit building function from {source_file.name}")
        elif res.returncode != 0:
            err_msg = res.stderr.strip() if res.stderr.strip() else res.stdout.strip()
            raise RuntimeError(f"Circuit generation failed in isolated worker:\n{err_msg}")
            
        with open(qpy_out, 'rb') as f:
            qc = qpy.load(f)[0]
        return qc
    except subprocess.TimeoutExpired:
        raise RuntimeError("Circuit generation timed out after 10 seconds.")
    finally:
        if os.path.exists(qpy_out):
            os.remove(qpy_out)
