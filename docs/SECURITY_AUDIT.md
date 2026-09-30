# Security audit - 2026-09-30

Scope: source tree prepared for the initial private GitHub publication of
THRIVEBERG Terminal 0.5.0 Beta.

## Results

- `pytest`: 224 passed.
- `pip-audit`: no known vulnerable installed dependencies.
- Bandit: no medium- or high-severity findings after hardening.
- `detect-secrets`: no private credentials found. Seven reviewed findings are
  the intentionally public Supabase publishable key and synthetic test values.
- Installer SHA-256: `30ADCBF2C32D329DD9FA80090B3B18EEBB24E5020D73ED014724C7EA15699D0C`.
- Microsoft Defender custom scan: zero detections for the Beta 010 installer.
- Packaged smoke test: successful 1920x1040 render with non-empty market data.

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

- Beta 010 is not code signed. SHA-256 verification detects modification but
  does not establish publisher identity.
- Public market-data endpoints can be delayed, rate limited, changed, or
  unavailable. Quality labels must remain visible and are not a trading SLA.
- Social-service security depends on deploying the checked-in RLS schema and on
  the Supabase project configuration remaining consistent with it.
- No finite review can guarantee that software is completely vulnerability-free.
