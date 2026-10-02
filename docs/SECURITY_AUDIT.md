# Security audit - 2026-10-02

Scope: THRIVEBERG Terminal 0.5.0 Beta 013 source tree, packaged application and
Windows installer.

## Results

- `pytest`: 238 passed.
- `pip-audit`: no known vulnerable installed dependencies.
- Bandit: no medium- or high-severity findings after hardening.
- `detect-secrets`: no new findings in the changed source, test or documentation files.
- Installer SHA-256: `DC9859EB57C8AA40AED0F5762CCBD1B83A6F39FA56AF9B680C6F698F648A59DD`.
- Microsoft Defender custom scan: zero detections for the Beta 013 installer.
- Packaged smoke tests: successful `DQM` provider dashboard and live `DQM AAPL`
  cross-source comparison renders at 1920x1040.
- Local `UPD` inventory: Beta 013 detected first with a verified checksum while
  Betas 012 and 011 remain available.

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

- Beta 013 is not code signed. SHA-256 verification detects modification but
  does not establish publisher identity.
- Public market-data endpoints can be delayed, rate limited, changed, or
  unavailable. Quality labels must remain visible and are not a trading SLA.
- Social-service security depends on deploying the checked-in RLS schema and on
  the Supabase project configuration remaining consistent with it.
- No finite review can guarantee that software is completely vulnerability-free.
