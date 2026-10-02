# Security audit - 2026-10-02

Scope: THRIVEBERG Terminal 0.5.0 Beta 018 source tree, packaged application and
Windows installer.

## Results

- `pytest`: 290 passed.
- `pip-audit`: no known vulnerable installed dependencies.
- Bandit: no medium- or high-severity findings after hardening.
- `detect-secrets`: no new findings in the changed source, test or documentation files.
- Installer SHA-256: `E0DF035854BE9E47B4B7BD1545862391F6AF87C8C76B7787A671B96CBF594CE4`.
- Packaged executable SHA-256: `6AB89E9B3FC36FB1931B19559631154F556F775F7D954957A80128CFD7A5477F`.
- Microsoft Defender custom scans: zero detections for the Beta 018 installer
  and packaged executable.
- Packaged and installed smoke tests: successful `DIAG` and `UPD` renders at
  1920x1080. The installed build reports 0.5.0 Beta 018 and all 11 diagnostic
  checks pass.
- The Ed25519 release manifest was verified against the bundled public key. Its
  signed installer name, byte size and SHA-256 all match the generated setup;
  tamper, downgrade, path traversal and interrupted-download cases are covered
  by automated tests.

## Hardening included

- Untrusted XML is parsed with `defusedxml`.
- Provider downloads require HTTPS; fixed providers use hostname allowlists.
- Local/private IP URLs, embedded URL credentials, and non-HTTPS browser links
  are rejected.
- Alert state transitions and feed deduplication use transactional SQLite
  writes, preventing duplicate events from concurrent foreground/background
  checks.
- Alert results from an old authenticated session are ignored after logout.
- Private settings use a versioned per-user Windows DPAPI envelope. V1 stores
  migrate transactionally to V2 with encrypted backup and rollback.
- Diagnostics export only sanitized metadata and recent redacted log output;
  database contents, portfolio values and credential values are excluded.
- Online updates are accepted only from the public binary repository after an
  Ed25519 signature, exact size and SHA-256 verification. Cached installers are
  revalidated before launch.
- Supabase anonymous table access and public function execution are revoked;
  authenticated access remains governed by row-level security.
- CI repeats tests, dependency audit, secret checks, and Bandit on every change.

## Residual risks

- Beta 018 is not Authenticode signed, so Windows SmartScreen can still warn on
  the initial installer. The in-app Ed25519 trust root authenticates subsequent
  THRIVEBERG update manifests independently of GitHub transport.
- Public market-data endpoints can be delayed, rate limited, changed, or
  unavailable. Quality labels must remain visible and are not a trading SLA.
- Social-service security depends on deploying the checked-in RLS schema and on
  the Supabase project configuration remaining consistent with it.
- No finite review can guarantee that software is completely vulnerability-free.
