import json
import base64
import hashlib
from pathlib import Path
from google.cloud import kms
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from quantumd.evidence.builder import sha256_file

class AuthorizationEngine:
    LOCAL_SIMULATION_DECISIONS = {
        "VERIFIED_FOR_EXECUTION",
        "VERIFIED_FOR_LOCAL_SIMULATION",
        "VERIFIED_EDUCATIONAL_ONLY",
    }
    
    QPU_DECISIONS = {
        "VERIFIED_FOR_EXECUTION",
        "VERIFIED_FOR_QPU_EXECUTION",
    }

    @staticmethod
    def authorize(project_dir: Path, evidence_run: str, target: str) -> dict:
        record_path = project_dir / "evidence" / "runs" / f"{evidence_run}.json"
        if not record_path.exists():
            raise PermissionError(f"Evidence record {evidence_run} not found.")
            
        evidence = json.loads(record_path.read_text(encoding="utf-8"))
        
        integrity = evidence.get("integrity", {})
        if not integrity.get("signed"):
            raise PermissionError("Evidence record is not signed.")
            
        declared_hash = integrity.get("canonical_payload_sha256")
        stripped = dict(evidence)
        stripped["integrity"] = {}
        canonical = json.dumps(stripped, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        actual_hash = hashlib.sha256(canonical).hexdigest()
        
        if actual_hash != declared_hash:
            raise PermissionError("EVIDENCE_COMPROMISED: Payload hash mismatch.")
            
        key_version_name = integrity.get("key_version")
        signature_base64 = integrity.get("value_base64")
        if not key_version_name or not signature_base64:
            raise PermissionError("Incomplete signature metadata.")
            
        client = kms.KeyManagementServiceClient()
        try:
            pub_key_response = client.get_public_key(name=key_version_name)
            pub_key = load_pem_public_key(pub_key_response.pem.encode("utf-8"))
            sig_bytes = base64.b64decode(signature_base64)
            pub_key.verify(sig_bytes, canonical, ec.ECDSA(hashes.SHA256()))
        except Exception as e:
            raise PermissionError(f"Cryptographic signature verification failed: {e}")
            
        decision = evidence.get("final_decision", "")
        if target == "aer-simulator":
            if decision not in AuthorizationEngine.LOCAL_SIMULATION_DECISIONS:
                raise PermissionError(f"INSUFFICIENT_AUTHORIZATION: Simulation requires {AuthorizationEngine.LOCAL_SIMULATION_DECISIONS}. Got: {decision}")
        elif target.startswith("ibm:"):
            if decision not in AuthorizationEngine.QPU_DECISIONS:
                raise PermissionError(f"INSUFFICIENT_AUTHORIZATION: QPU execution requires {AuthorizationEngine.QPU_DECISIONS}. Got: {decision}")
        else:
            raise PermissionError(f"Unknown target: {target}")
            
        return {"evidence": evidence, "payload_hash": actual_hash}

    @staticmethod
    def check_snapshot(snapshot_dir: Path, evidence: dict):
        manifest_hash = sha256_file(snapshot_dir / "experiment.yaml")
        verified_manifest_hash = evidence.get("hashes", {}).get("manifest_sha256")
        if manifest_hash != verified_manifest_hash:
            raise PermissionError(f"Manifest Identity Hash Mismatch. Verified: {verified_manifest_hash} Snapshot: {manifest_hash}")
            
        source_info = evidence.get("hashes", {}).get("source", {})
        source_path = snapshot_dir / source_info.get("path", "")
        if not source_path.exists():
            raise PermissionError("Verified source file missing from snapshot.")
            
        source_hash = sha256_file(source_path)
        if source_hash != source_info.get("sha256"):
            raise PermissionError(f"Source Identity Hash Mismatch (Tampering detected). Verified: {source_info.get('sha256')} Snapshot: {source_hash}")
