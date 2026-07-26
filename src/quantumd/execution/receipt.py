import json
import os
import uuid
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from qiskit import qpy, QuantumCircuit
from quantumd.evidence.builder import sha256_file
from quantumd.evidence.signing import sign_payload_with_kms

class ExecutionReceiptBuilder:
    def __init__(self, project_dir: Path, verification_run_id: str, verification_payload_sha256: str):
        self.project_dir = project_dir.resolve()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        self.exec_id = f"QEXEC-{timestamp}-{uuid.uuid4().hex[:8]}"
        
        self.exec_dir = self.project_dir / "evidence" / "executions" / self.exec_id
        self.exec_dir.mkdir(parents=True, exist_ok=True)
        
        self.receipt = {
            "schema_version": "quantumd.ai/execution/v0.1",
            "execution_id": self.exec_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "authorization": {
                "verification_run_id": verification_run_id,
                "verification_payload_sha256": verification_payload_sha256,
                "signature_verified": True
            },
            "workload": {},
            "target": {},
            "status": "PENDING",
            "integrity": {}
        }

    def set_workload(self, manifest_hash: str, source_hash: str, logical_qc: QuantumCircuit, transpiled_qc: QuantumCircuit, seed: int):
        self.receipt["workload"] = {"manifest_sha256": manifest_hash, "source_sha256": source_hash}
        
        log_path = self.exec_dir / "logical-circuit.qpy"
        comp_path = self.exec_dir / "executed-circuit.qpy"
        
        with open(log_path, 'wb') as f: qpy.dump(logical_qc, f)
        with open(comp_path, 'wb') as f: qpy.dump(transpiled_qc, f)
        
        self.receipt["workload"]["logical_circuit"] = {"format": "QPY", "sha256": sha256_file(log_path)}
        self.receipt["workload"]["executed_circuit"] = {
            "format": "QPY", 
            "sha256": sha256_file(comp_path), 
            "transpiler_seed": seed,
            "optimization_level": 1
        }

    def record_denial(self, denial_code: str, reason: str, allow_unsigned: bool = False) -> Path:
        self.receipt["status"] = "EXECUTION_DENIED_PRECHECK"
        self.receipt["denial_code"] = denial_code
        self.receipt["details"] = reason
        self.receipt["workload_executed"] = False
        return self._finalize(allow_unsigned)
        
    def record_failure(self, failure_code: str, reason: str, allow_unsigned: bool = False) -> Path:
        self.receipt["status"] = "EXECUTION_FAILED"
        self.receipt["failure_code"] = failure_code
        self.receipt["details"] = reason
        self.receipt["workload_executed"] = True
        return self._finalize(allow_unsigned)

    def record_success(self, target: str, shots: int, counts: dict, allow_unsigned: bool = False) -> Path:
        self.receipt["status"] = "EXECUTION_COMPLETED"
        self.receipt["shots"] = shots
        self.receipt["target"] = {"provider": "local", "backend": target, "simulation_method": "automatic"}
        self.receipt["workload_executed"] = True
        
        res_path = self.exec_dir / "results.json"
        res_path.write_text(json.dumps(counts, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        
        self.receipt["results"] = {"artifact": "results.json", "sha256": sha256_file(res_path)}
        return self._finalize(allow_unsigned)

    def _finalize(self, allow_unsigned: bool) -> Path:
        canonical = json.dumps(self.receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        receipt_hash = hashlib.sha256(canonical).hexdigest()
        
        kms_key = os.environ.get("QUANTUMD_KMS_KEY_VERSION")
        if kms_key:
            sig_data = sign_payload_with_kms(
                receipt_hash,
                kms_key,
                evidence_root=self.project_dir / "evidence",
            )
            self.receipt["integrity"] = {"canonical_payload_sha256": receipt_hash, **sig_data}
            if not sig_data.get("signed"):
                self.receipt["status"] = f"{self.receipt['status']}_ATTESTATION_FAILED"
        else:
            if not allow_unsigned:
                self.receipt["status"] = f"{self.receipt['status']}_ATTESTATION_FAILED"
            self.receipt["integrity"] = {"canonical_payload_sha256": receipt_hash, "signed": False, "signature_status": "NO_KEY_PROVIDED"}

        filepath = self.exec_dir / "receipt.json"
        fd = os.open(filepath, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(self.receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
        return filepath
