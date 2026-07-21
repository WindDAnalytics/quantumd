import base64
import json
from pathlib import Path
from google.cloud import kms
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from cryptography.exceptions import InvalidSignature

def verify_signature(project_dir: Path) -> dict:
    latest_pointer = project_dir / "evidence" / "latest.json"
    if not latest_pointer.exists():
        raise FileNotFoundError(f"No evidence pointer found in {project_dir}")
        
    pointer = json.loads(latest_pointer.read_text(encoding="utf-8"))
    record_path = project_dir / pointer["record"]
    evidence = json.loads(record_path.read_text(encoding="utf-8"))
    
    integrity = evidence.get("integrity", {})
    if not integrity.get("signed"):
        raise ValueError("The evidence record is not signed.")
        
    key_version_name = integrity.get("key_version")
    signature_base64 = integrity.get("value_base64")
    declared_hash_hex = integrity.get("canonical_payload_sha256")
    
    if not all([key_version_name, signature_base64, declared_hash_hex]):
        raise ValueError("Incomplete signature metadata in evidence record.")
        
    # Strip the integrity block to rebuild the canonical payload for verification
    stripped_evidence = dict(evidence)
    stripped_evidence["integrity"] = {}
    
    canonical_payload = json.dumps(
        stripped_evidence,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    
    import hashlib
    actual_hash_hex = hashlib.sha256(canonical_payload).hexdigest()
    
    if actual_hash_hex != declared_hash_hex:
        raise ValueError(f"Payload hash mismatch!\nDeclared: {declared_hash_hex}\nActual:   {actual_hash_hex}")

    # Fetch the public key from GCP KMS
    client = kms.KeyManagementServiceClient()
    try:
        public_key_response = client.get_public_key(name=key_version_name)
    except Exception as e:
        raise RuntimeError(f"Failed to fetch public key from KMS: {e}")
        
    # Verify the ECDSA signature mathematically
    try:
        pem = public_key_response.pem.encode("utf-8")
        pub_key = load_pem_public_key(pem)
        
        signature_bytes = base64.b64decode(signature_base64)
        
        # KMS EC_SIGN_P256_SHA256 uses ECDSA with SHA256
        pub_key.verify(
            signature_bytes,
            canonical_payload,
            ec.ECDSA(hashes.SHA256())
        )
        
        # The underlying record is immutable (0o444) by design.
        # We update the mutable pointer (latest.json) to reflect offline verification status.
        pointer_data = json.loads(latest_pointer.read_text(encoding="utf-8"))
        pointer_data["public_key_signature_verified"] = True
        pointer_data["signature_status"] = "PUBLIC_KEY_VERIFIED"
        latest_pointer.write_text(json.dumps(pointer_data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        
        return {
            "status": "VALID",
            "run_id": evidence["run_id"],
            "hash": actual_hash_hex,
            "key_version": key_version_name
        }
        
    except InvalidSignature:
        raise ValueError("CRYPTOGRAPHIC FAILURE: Signature is mathematically invalid.")
    except Exception as e:
        raise RuntimeError(f"Verification process failed: {e}")
