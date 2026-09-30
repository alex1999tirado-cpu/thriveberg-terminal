# Security Policy

## Supported version

Security fixes are applied to the latest beta and the current `main` branch.
Older beta installers are not supported.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability or leaked credential.
Use the repository's private security-advisory form under **Security > Advisories**.
Include the affected version, reproduction steps, impact, and any suggested fix.

## Security model

- Private provider keys are never committed or bundled. On Windows they are
  stored per user with DPAPI in `secure-settings.bin`.
- The bundled Supabase value is a publishable desktop-client key. Authorization
  is enforced by Supabase Auth and the RLS policies in `supabase/social_schema.sql`.
- Network providers accept HTTPS endpoints only; fixed providers additionally
  enforce host allowlists.
- External links are opened only after HTTPS validation.
- Release installers are currently unsigned. Verify the published SHA-256 before
  running them and expect Microsoft SmartScreen to warn until code signing is added.

No software can be guaranteed completely secure. The test suite, dependency
audit, static analysis, secret review, RLS, and checksum validation reduce risk
but do not replace independent review or code signing.
