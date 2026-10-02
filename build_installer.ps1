param(
    [ValidatePattern('^\d{3}$')]
    [string]$BetaVersion = "017",
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$AppVersion = "0.5.0"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root ".venv_gui\Scripts\python.exe"
$spec = Join-Path $root "THRIVEBERG_INSTALLER.spec"
$iss = Join-Path $root "installer\THRIVEBERG.iss"
$releaseDirectory = Join-Path $root "releases\BETA"
$setup = Join-Path $releaseDirectory "THRIVEBERG-Terminal-BETA-$BetaVersion-Setup.exe"
$versionFile = Join-Path $root "build\installer_version_info.txt"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "The GUI build environment is missing: $python"
}

$iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source
if (-not $iscc) {
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    )
    $iscc = $candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
}
if (-not $iscc) {
    throw "Inno Setup 6 was not found. Install it with: winget install JRSoftware.InnoSetup"
}

$versionParts = $AppVersion.Split('.') | ForEach-Object { [int]$_ }
$versionResource = @"
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($($versionParts[0]), $($versionParts[1]), $($versionParts[2]), 0),
    prodvers=($($versionParts[0]), $($versionParts[1]), $($versionParts[2]), 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0),
  ),
  kids=[
    StringFileInfo([
      StringTable(
        u'040904B0',
        [StringStruct(u'CompanyName', u'THRIVEBERG'),
         StringStruct(u'FileDescription', u'THRIVEBERG Terminal'),
         StringStruct(u'FileVersion', u'$AppVersion Beta'),
         StringStruct(u'InternalName', u'THRIVEBERG_Terminal'),
         StringStruct(u'LegalCopyright', u'Copyright THRIVEBERG contributors'),
         StringStruct(u'OriginalFilename', u'THRIVEBERG_Terminal.exe'),
         StringStruct(u'ProductName', u'THRIVEBERG Terminal'),
         StringStruct(u'ProductVersion', u'$AppVersion Beta')])
    ]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"@
[System.IO.Directory]::CreateDirectory((Split-Path -Parent $versionFile)) | Out-Null
[System.IO.File]::WriteAllText($versionFile, $versionResource, [System.Text.UTF8Encoding]::new($false))
$previousVersionFile = $env:THRIVEBERG_VERSION_FILE
$env:THRIVEBERG_VERSION_FILE = $versionFile

Push-Location $root
try {
    Write-Host "[1/4] Running the complete test suite..." -ForegroundColor Cyan
    & $python -m pytest --basetemp=build\pytest-installer
    if ($LASTEXITCODE -ne 0) { throw "Tests failed" }

    Write-Host "[2/4] Building the installed application directory..." -ForegroundColor Cyan
    & $python -m PyInstaller --noconfirm --clean $spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

    Write-Host "[3/4] Compiling the versioned installer..." -ForegroundColor Cyan
    & $iscc "/DBetaVersion=$BetaVersion" "/DAppVersion=$AppVersion" $iss
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }

    Write-Host "[4/4] Writing the release checksum..." -ForegroundColor Cyan
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $setup).Hash
    $checksum = "$hash  $([System.IO.Path]::GetFileName($setup))`n"
    [System.IO.File]::WriteAllText(
        [System.IO.Path]::ChangeExtension($setup, ".sha256"),
        $checksum,
        [System.Text.UTF8Encoding]::new($false)
    )
}
finally {
    Pop-Location
    if ($null -eq $previousVersionFile) {
        Remove-Item Env:THRIVEBERG_VERSION_FILE -ErrorAction SilentlyContinue
    }
    else {
        $env:THRIVEBERG_VERSION_FILE = $previousVersionFile
    }
}

Write-Host "Installer ready: $setup" -ForegroundColor Green
