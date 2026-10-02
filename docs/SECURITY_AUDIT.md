# Security audit - 2026-10-02

Scope: THRIVEBERG Terminal 0.5.0 Beta 016 source tree, packaged application and
Windows installer.

## Results

- `pytest`: 264 passed.
- `pip-audit`: no known vulnerable installed dependencies.
- Bandit: no medium- or high-severity findings after hardening.
- `detect-secrets`: no new findings in the changed source, test or documentation files.
- Installer SHA-256: `ECA70A9D14E368F8FAF5AD5E625F6AEA4BBEE5917B5F65559F5BB2994401B775`.
- Packaged executable SHA-256: `031854CCA3EC62C1F5EC10BEE6242E9B3D04D5A373C464CCBD31C759D0E85370`.
- Microsoft Defender custom scans: zero detections for the Beta 016 installer
  and packaged executable.
- Packaged smoke test: successful `PORT MAIN ACTIONS REFRESH` and
  `PORT MAIN ACTIONS APPLY` renders at 1920x1080 using an isolated AAPL ledger.
  Three observed dividends were applied once for USD 80 total; a second apply
  produced zero new entries and preserved quantity and cost basis.
- Local `UPD` inventory: Beta 016 staged with a verified checksum while Beta 015
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

- Beta 016 is not code signed. SHA-256 verification detects modification but
  does not establish publisher identity.
- Public market-data endpoints can be delayed, rate limited, changed, or
  unavailable. Quality labels must remain visible and are not a trading SLA.
- Social-service security depends on deploying the checked-in RLS schema and on
  the Supabase project configuration remaining consistent with it.
- No finite review can guarantee that software is completely vulnerability-free.
