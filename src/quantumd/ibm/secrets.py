from __future__ import annotations

from dataclasses import dataclass

import google.auth
import google_crc32c
from google.cloud import secretmanager


@dataclass(frozen=True)
class SecretValue:
    value: str
    version_name: str


def access_secret(
    secret_id: str,
    version: str = "latest",
) -> SecretValue:
    """
    Retrieve one Secret Manager version using ADC and verify its CRC32C.

    The returned version_name is concrete even when the caller requests
    the 'latest' alias. Plans must bind to this exact version.
    """
    _, project_id = google.auth.default()

    if not project_id:
        raise RuntimeError(
            "Unable to resolve the active Google Cloud project."
        )

    name = (
        f"projects/{project_id}/secrets/{secret_id}/"
        f"versions/{version}"
    )

    client = secretmanager.SecretManagerServiceClient()
    response = client.access_secret_version(
        request={"name": name}
    )

    payload = response.payload.data

    checksum = google_crc32c.Checksum()
    checksum.update(payload)
    calculated_crc32c = int(checksum.hexdigest(), 16)

    if response.payload.data_crc32c != calculated_crc32c:
        raise RuntimeError(
            "Secret Manager payload CRC32C verification failed."
        )

    value = payload.decode("utf-8").strip()

    if not value:
        raise RuntimeError(
            f"Secret {secret_id!r} version is empty."
        )

    return SecretValue(
        value=value,
        version_name=response.name,
    )
