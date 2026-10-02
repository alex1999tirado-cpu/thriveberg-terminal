# THRIVEBERG Terminal Beta Releases

This directory contains local distributable beta artifacts. Generated binaries
and checksums are excluded from Git history and published as release assets.

## BETA 013

- File: `THRIVEBERG-Terminal-BETA-013-Setup.exe`
- Released: 2026-10-02
- Status: Current beta / distributable Windows installer
- Version: 0.5.0 Beta
- Highlight: native `DQM` data-quality monitor with provider health, persistent probe history, cache inventory, coverage matrix and cross-source quote comparison
- Validation: 238 automated tests, dependency audit, changed-file secret scan, static security analysis, packaged `DQM` and `DQM AAPL` smoke tests, checksum verification, and Microsoft Defender scan
- SHA-256: `DC9859EB57C8AA40AED0F5762CCBD1B83A6F39FA56AF9B680C6F698F648A59DD`
- Security: no private provider credentials are bundled; user-supplied keys are stored with Windows DPAPI.

The next development build is `BETA 014`. Generated installers and checksums
should be published as GitHub Release assets rather than committed to source.
