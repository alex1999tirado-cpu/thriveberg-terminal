# Security audit - 2026-10-02

Scope: THRIVEBERG Terminal 0.5.0 Beta 015 source tree, packaged application and
Windows installer.

## Results

- `pytest`: 255 passed.
- `pip-audit`: no known vulnerable installed dependencies.
- Bandit: no medium- or high-severity findings after hardening.
- `detect-secrets`: no new findings in the changed source, test or documentation files.
- Installer SHA-256: `56956160B0829FA9AA2332D20B3D3C7AA719C1D1509D16F24DC8B6DBC9DD2619`.
- Packaged executable SHA-256: `65A344875DDF8D8BF1527A965B34E48042E7F596DDEDA6D6BE96F548CB66F3CF`.
- Microsoft Defender custom scans: zero detections for the Beta 015 installer
  and packaged executable.
- Packaged smoke test: successful `PORT MAIN RISK SPY 1Y` render at 1920x1080
  using an isolated multi-currency ledger, 247 observed sessions, historical FX
  conversion and 100% market-value history coverage.
- Local `UPD` inventory: Beta 015 staged with a verified checksum while Beta 014
  remains available.

## Hardening included

- Untrusted XML is parsed with `defusedxml`.
- Provider downloads require HTTPS; fixed providers use hostname allowlists.
- Local/private IP URLs, embedded URL credentials, and non-HTTPS browser links
  are rejected.
- SQLite alert queries do not interpolate SQL fragments.
- Private settings use per-user Windows DPAPI storage.
- Supabase anonymous table access and public function execution are revoked;
  authenticated access remains governed by row-level security.
- CI repeats tests, dependency audit, secret checks, and Bandit on every change.

## Residual risks

- Beta 015 is not code signed. SHA-256 verification detects modification but
  does not establish publisher identity.
- Public market-data endpoints can be delayed, rate limited, changed, or
  unavailable. Quality labels must remain visible and are not a trading SLA.
- Social-service security depends on deploying the checked-in RLS schema and on
  the Supabase project configuration remaining consistent with it.
- No finite review can guarantee that software is completely vulnerability-free.
