# Trust modes

QuantumD separates local development from real hardware authority.

## `UNCONFIGURED`

No valid signing provider is available. Governed execution is denied.

## `LOCAL_DEVELOPMENT`

Available now.

- Project-local signing identity.
- Aer simulation only.
- Offline verification.
- No GCP requirement.
- No IBM contact.
- Hardware authorization prohibited.

## `KMS_GOVERNED`

Available for the existing organization-managed execution path.

- Organization-controlled signing through Google Cloud KMS.
- Managed approval and evidence lineage.
- IBM hardware execution subject to policy and account access.
- Intended for controlled production workflows.

When KMS is configured, it takes precedence over local-development trust.

## `SELF_MANAGED_HARDWARE`

Planned for Phase 5B.

This mode will allow a developer to use an encrypted local signing
identity and their own IBM Quantum account without requiring GCP.

Planned controls include:

- Explicit hardware enablement.
- Encrypted IBM credential storage.
- Signing-key creation and import.
- Backend and shot limits.
- Cost ceilings.
- Expiring, single-use approval.
- Exact workload and result binding.

A `LOCAL_DEVELOPMENT` identity will never automatically gain this scope.
