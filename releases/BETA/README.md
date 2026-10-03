# THRIVEBERG Terminal Beta Releases

This directory contains local distributable beta artifacts. Generated binaries
and checksums are excluded from Git history and published as release assets.

## BETA 021

- File: `THRIVEBERG-Terminal-BETA-021-Setup.exe`
- Released: 2026-10-03
- Status: Current beta / distributable Windows installer
- Version: 0.5.0 Beta
- Highlight: automatic configurable 2 x 2 Global Overview with independent EURUSD, world-equity, sovereign-rate and market-news workspaces on the selected display
- Validation: 305 automated tests, dependency audit, secret scan, static security analysis, packaged and installed `DIAG` smoke tests, Ed25519 manifest verification, checksum verification, and Microsoft Defender scan
- SHA-256: `5E0970E781703CECE6DD48DB6AA38B30D53B4A8B8C218D1FF08B65C2D3F832C3`
- Security: no private provider credentials are bundled; user-supplied keys are stored with Windows DPAPI.

The next development build is `BETA 022`. Generated installers and checksums
should be published as GitHub Release assets rather than committed to source.
