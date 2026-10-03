# THRIVEBERG Windows Installer

The installed edition uses a PyInstaller one-directory bundle and an Inno Setup
per-user installer. Every release keeps the same Inno Setup `AppId`, so installing
a newer build upgrades the existing application directory while retaining user
data under `%LOCALAPPDATA%\THRIVEBERG Terminal`.

Private API credentials are not bundled in the installer. THRIVEBERG stores any
user-supplied private provider keys in `secure-settings.bin`, encrypted with
Windows DPAPI for the current Windows account. Legacy recognized values in
`.env` are migrated and removed at startup.

The shared Supabase URL and publishable client key are included so a clean
installation can create an account and sign in immediately. They are public
desktop-client identifiers, not privileged credentials; database access remains
restricted by Supabase Auth and Row Level Security. Secret and `service_role`
keys must never be added to the installer.

Beta 022 is the current distributable build. Build the next beta from a clean
Git working tree with:

```powershell
.\build_installer.ps1
```

The script defaults to Beta 023 and application version 0.5.0. Use explicit
parameters for later releases.

Validate an installer with `tools\smoke_installer.ps1`. The script waits for
Inno Setup to finish before it starts the installed executable; launching the
application while Setup is still expanding the one-directory bundle is also
guarded by `.thriveberg-installing`, so the launcher cannot import an incomplete
Qt runtime.

The build requires the release signing key at
`%LOCALAPPDATA%\THRIVEBERG Terminal\release-signing-key.bin`. That private key is
encrypted with Windows DPAPI and must never enter source control. The matching
Ed25519 public key is bundled with the application.

Do not commit generated installers to the source repository. Publish the setup
executable, `.sha256`, `.update.json`, and `.update.json.sig` files together as
GitHub Release assets in the public binary-only distribution repository. `UPD`
trusts the Ed25519 signature and then checks the signed installer size and
SHA-256 before launch. Authenticode is a separate future requirement, so Windows
SmartScreen may still warn about the publisher.

Private settings use the versioned DPAPI V2 envelope. A V1 encrypted store is
backed up in encrypted form, migrated atomically and verified before use. Legacy
recognized `.env` values are copied into DPAPI and scrubbed without creating a
plaintext backup.
