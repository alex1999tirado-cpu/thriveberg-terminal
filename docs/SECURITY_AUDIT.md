# Security audit - 2026-10-03

Scope: THRIVEBERG Terminal 0.5.0 Beta 022 source tree, packaged application and
Windows installer.

## Results

- `pytest`: 311 passed, with 21 third-party deprecation warnings.
- `pip-audit`: no known vulnerable installed dependencies.
- Bandit: no medium- or high-severity findings after hardening.
- `detect-secrets`: no unreviewed findings. The public SHA-256 values in the
  DOOM integrity manifest are recorded as audited false positives.
- Installer SHA-256: `AC0CC12201E9CBDEF8A3F77EB296955180C664568121FB31753BBF2B69AA80D7`.
- Installed executable SHA-256: `C8AB88A5A1DD40A0DD9CCA7A7639BDD2F70C0722EED76E0C68E44C4A3F27F31C`.
- Microsoft Defender custom scans: zero detections for the Beta 022 installer
  and installed executable.
- Packaged and installed smoke tests: successful `DIAG` render at 1920x1080.
  The installed build reports 0.5.0 Beta 022 from commit `41982ddee52b`, with
  11 checks passed and no failures or warnings.
- Global Overview coverage verifies persisted display/panel configuration,
  recursive-command rejection, four independent compact workspaces and
  double-click expansion/restoration of the complete 2 x 2 market wall.
- Workspace-tab coverage verifies independent securities and live widgets,
  route ownership during background loads, session restoration, and secondary
  terminal-window cleanup for multi-monitor use.
- World bond market coverage verifies the provider-backed 17-country matrix,
  regional filters, country term structures, chart drill-down and compact wall
  rendering without presenting unavailable observations as real data.
- The installer handoff was tested by starting the frozen application while the
  update marker existed. Startup waited for marker removal and then completed,
  preventing imports from a partially replaced Qt runtime.
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
- The bundled Chocolate Doom/Freedoom runtime is validated against a SHA-256
  manifest before launch. Game configuration and save files remain in the
  current user's local application-data directory.
- Supabase anonymous table access and public function execution are revoked;
  authenticated access remains governed by row-level security.
- CI repeats tests, dependency audit, secret checks, and Bandit on every change.

## Residual risks

- Beta 022 is not Authenticode signed, so Windows SmartScreen can still warn on
  the initial installer. The in-app Ed25519 trust root authenticates subsequent
  THRIVEBERG update manifests independently of GitHub transport.
- Public market-data endpoints can be delayed, rate limited, changed, or
  unavailable. Quality labels must remain visible and are not a trading SLA.
- Social-service security depends on deploying the checked-in RLS schema and on
  the Supabase project configuration remaining consistent with it.
- No finite review can guarantee that software is completely vulnerability-free.
