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

Beta 012 is the current distributable build. Build the next beta with:

```powershell
.\build_installer.ps1
```

The script defaults to Beta 013 and application version 0.5.0. Use explicit
parameters for later releases.

Do not commit generated installers to the source repository. Publish the setup
executable and its generated `.sha256` file together as GitHub Release assets.
The current beta is unsigned, so recipients should verify the checksum before
running it and may still see a Microsoft SmartScreen warning.
