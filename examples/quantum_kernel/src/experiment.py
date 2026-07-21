from qiskit import QuantumCircuit

def get_circuit():
    """
    A plausible AI-generated circuit, but it contains 
    a fatal physical defect: applying a gate after a measurement.
    """
    qc = QuantumCircuit(2, 2)
    
    # State preparation
    qc.h(0)
    
    
    # Attempting to entangle a collapsed qubit (Invalid on physical QPUs!)
    qc.cx(0, 1)
    
    qc.measure(0, 0)
    qc.measure(1, 1)
    
    return qc
