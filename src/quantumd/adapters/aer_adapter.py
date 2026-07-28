from qiskit_aer import AerSimulator
from qiskit import transpile, QuantumCircuit

def execute_on_aer(qc: QuantumCircuit, shots: int, seed: int = 1729) -> tuple[dict, QuantumCircuit]:
    if len(qc.cregs) == 0 or sum(creg.size for creg in qc.cregs) == 0:
        raise ValueError("OUTPUT_CONTRACT_UNSATISFIED: Authorized circuit contains no classical registers for measurement.")
        
    simulator = AerSimulator()
    compiled_circuit = transpile(qc, simulator, optimization_level=1, seed_transpiler=seed)
    job = simulator.run(compiled_circuit, shots=shots, seed_simulator=seed)
    
    result = job.result()
    if not result.success:
         raise RuntimeError(f"Aer execution failed: {result.status}")

    try:
        counts = result.get_counts()
        if isinstance(counts, list):
            counts = counts[0]
    except Exception:
        counts = {}
        
    return counts, compiled_circuit
