import time
from qiskit import QuantumCircuit
import warnings

# Suppress MQT QCEC warnings for clean CLI output
warnings.filterwarnings("ignore")

try:
    from mqt import qcec
except ImportError:
    qcec = None

def check_equivalence(original_qc: QuantumCircuit, candidate_qc: QuantumCircuit) -> dict:
    """
    Compares two Qiskit QuantumCircuits using MQT QCEC.
    """
    if qcec is None:
        return {
            "gate": "repair_equivalence",
            "status": "ERROR",
            "decision": "NOT_APPLICABLE",
            "details": {"error_message": "mqt.qcec package is not installed."}
        }
        
    start_time = time.perf_counter()
    try:
        # Modern MQT QCEC 3.x API: Pass configs directly as kwargs
        result = qcec.verify(
            original_qc, 
            candidate_qc, 
            transform_dynamic_circuit=True
        )
        
        raw_result = result.equivalence.name
        
        if raw_result == "equivalent":
            decision = "EQUIVALENT"
            status = "PASS"
        elif raw_result == "equivalent_up_to_global_phase":
            decision = "EQUIVALENT"
            status = "PASS"
        elif raw_result == "not_equivalent":
            decision = "NOT_EQUIVALENT"
            status = "FAIL"
        else:
            decision = "INCONCLUSIVE"
            status = "FAIL"
            
        duration_ms = int((time.perf_counter() - start_time) * 1000)
            
        return {
            "gate": "repair_equivalence",
            "status": status,
            "decision": decision,
            "comparison": {
                "method": "mqt-qcec",
                "mode": "strict",
                "dynamic_circuit_transformation": True,
                "duration_ms": duration_ms
            },
            "details": {
                "mqt_raw_result": raw_result
            }
        }
    except Exception as e:
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        return {
            "gate": "repair_equivalence",
            "status": "ERROR",
            "decision": "ERROR",
            "comparison": {
                "method": "mqt-qcec",
                "duration_ms": duration_ms
            },
            "details": {
                "error_message": type(e).__name__ + ": " + str(e)
            }
        }
