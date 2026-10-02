# Security audit - 2026-10-02

Scope: THRIVEBERG Terminal 0.5.0 Beta 017 source tree, packaged application and
Windows installer.

## Results

- `pytest`: 275 passed.
- `pip-audit`: no known vulnerable installed dependencies.
- Bandit: no medium- or high-severity findings after hardening.
- `detect-secrets`: no new findings in the changed source, test or documentation files.
- Installer SHA-256: `E1A944F639F1277451FA6658289D1578586AD484FB088CBF0F4D7F388A6543C2`.
- Packaged executable SHA-256: `A374A816D0A4453CE49A3725DC24954A8E572E560F824E42EDEDEBE9831820A4`.
- Microsoft Defender custom scans: zero detections for the Beta 017 installer
  and packaged executable.
- Packaged smoke test: successful `ALRT REFRESH` render at 1920x1080 using an
  isolated AAPL portfolio and six real-provider alert types. Market,
  fundamentals, corporate events and portfolio risk triggered once; filings
  and news initialized their existing feeds without replaying old items.
  A second refresh preserved exactly four events with zero evaluation errors.
- Local `UPD` inventory: Beta 017 staged with a verified checksum while six
  previous beta installers remain available.

## Hardening included

- Untrusted XML is parsed with `defusedxml`.
- Provider downloads require HTTPS; fixed providers use hostname allowlists.
- Local/private IP URLs, embedded URL credentials, and non-HTTPS browser links
  are rejected.
- Alert state transitions and feed deduplication use transactional SQLite
  writes, preventing duplicate events from concurrent foreground/background
  checks.
- Alert results from an old authenticated session are ignored after logout.
- Private settings use per-user Windows DPAPI storage.
- Supabase anonymous table access and public function execution are revoked;
  authenticated access remains governed by row-level security.
- CI repeats tests, dependency audit, secret checks, and Bandit on every change.

## Residual risks

- Beta 017 is not code signed. SHA-256 verification detects modification but
  does not establish publisher identity.
- Public market-data endpoints can be delayed, rate limited, changed, or
  unavailable. Quality labels must remain visible and are not a trading SLA.
- Social-service security depends on deploying the checked-in RLS schema and on
  the Supabase project configuration remaining consistent with it.
- No finite review can guarantee that software is completely vulnerability-free.
