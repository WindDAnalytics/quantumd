import json
import numpy as np
from qiskit import QuantumCircuit
from quantumd.adapters.mqt_adapter import check_equivalence

def evaluate(name, expected, qc1, qc2):
    res = check_equivalence(qc1, qc2)
    print(f"\n{name}")
    print(f"Expected: {expected}")
    print(f"Result:   {res.get('decision')} (MQT: {res.get('details', {}).get('mqt_raw_result', 'N/A')})")
    if res.get('status') == 'ERROR':
        print(f"Error: {res.get('details', {}).get('error_message')}")

def test_fixtures():
    print("--- GATE 4: SEMANTIC PRESERVATION & EQUIVALENCE CHECKING ---")

    # 1. Identical circuits
    qc1 = QuantumCircuit(2); qc1.h(0); qc1.cx(0, 1)
    qc2 = QuantumCircuit(2); qc2.h(0); qc2.cx(0, 1)
    evaluate("1. Identical circuits", "EQUIVALENT", qc1, qc2)

    # 2. Different decompositions
    qc3 = QuantumCircuit(1); qc3.h(0)
    qc4 = QuantumCircuit(1); qc4.ry(np.pi/2, 0); qc4.rx(np.pi, 0)
    evaluate("2. Different decompositions", "EQUIVALENT", qc3, qc4)

    # 3. Deliberately different circuits
    qc5 = QuantumCircuit(2); qc5.h(0); qc5.cx(0, 1)
    qc6 = QuantumCircuit(2); qc6.x(0); qc6.cx(0, 1)
    evaluate("3. Deliberately different", "NOT_EQUIVALENT", qc5, qc6)

    # 4. Same measured outputs with unused garbage qubits
    qc7 = QuantumCircuit(2, 1); qc7.h(0); qc7.measure(0, 0)
    qc8 = QuantumCircuit(2, 1); qc8.h(0); qc8.x(1); qc8.measure(0, 0)
    evaluate("4. Unused garbage qubits", "PARTIALLY_EQUIVALENT", qc7, qc8)

    # 5. Current premature-measurement repair (The Killer Demo)
    original = QuantumCircuit(2, 2)
    original.h(0)
    original.measure(0, 0)
    original.cx(0, 1)
    original.measure(1, 1)

    repaired = QuantumCircuit(2, 2)
    repaired.h(0)
    repaired.cx(0, 1)
    repaired.measure(0, 0)
    repaired.measure(1, 1)

    evaluate("5. qfix premature-measurement repair", "Let's find out!", original, repaired)

if __name__ == '__main__':
    test_fixtures()
