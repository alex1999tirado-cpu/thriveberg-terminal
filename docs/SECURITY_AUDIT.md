# Security audit - 2026-10-02

Scope: THRIVEBERG Terminal 0.5.0 Beta 014 source tree, packaged application and
Windows installer.

## Results

- `pytest`: 248 passed.
- `pip-audit`: no known vulnerable installed dependencies.
- Bandit: no medium- or high-severity findings after hardening.
- `detect-secrets`: no new findings in the changed source, test or documentation files.
- Installer SHA-256: `E337282CD0E833BC343E68E486586217A77DAE01C09051B4CCD96043DF5DE56A`.
- Packaged executable SHA-256: `6A071156C5A109F99BC7407E312394B7B4A0957C62759BFC6A71B6F49438758C`.
- Microsoft Defender custom scans: zero detections for the Beta 014 installer
  and packaged executable.
- Packaged smoke test: successful `PORT` render at 1920x1080 using an isolated
  multi-currency ledger with trades, realized P&L, income, fees and cash.
- Local `UPD` inventory: Beta 014 staged with a verified checksum while Beta 013
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

- Beta 014 is not code signed. SHA-256 verification detects modification but
  does not establish publisher identity.
- Public market-data endpoints can be delayed, rate limited, changed, or
  unavailable. Quality labels must remain visible and are not a trading SLA.
- Social-service security depends on deploying the checked-in RLS schema and on
  the Supabase project configuration remaining consistent with it.
- No finite review can guarantee that software is completely vulnerability-free.
