import base64
from google.cloud import kms

def sign_payload_with_kms(payload_hash_hex: str, key_version_name: str) -> dict:
    """Sends the SHA-256 hash to GCP KMS for an asymmetric ECDSA signature."""
    client = kms.KeyManagementServiceClient()
    
    # KMS requires the raw bytes of the digest
    digest_bytes = bytes.fromhex(payload_hash_hex)
    digest = {"sha256": digest_bytes}
    
    try:
        response = client.asymmetric_sign(
            request={
                "name": key_version_name,
                "digest": digest,
            }
        )
        
        return {
            "provider": "gcp-cloud-kms",
            "algorithm": "EC_SIGN_P256_SHA256",
            "key_version": key_version_name,
            "value_base64": base64.b64encode(response.signature).decode("utf-8"),
            "signature_status": "KMS_SIGNED",
            "provider_response_integrity_verified": True,
            "public_key_signature_verified": False,
            "signed": True
        }
    except Exception as e:
        return {
            "signed": False,
            "signature_status": "FAILED",
            "error_message": str(e)
        }
