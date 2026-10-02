param(
    [Parameter(Mandatory = $true)]
    [string]$Installer,
    [string]$Screenshot = ""
)

$ErrorActionPreference = "Stop"
$setup = (Resolve-Path -LiteralPath $Installer).Path
$installDir = Join-Path $env:LOCALAPPDATA "Programs\THRIVEBERG Terminal"
$executable = Join-Path $installDir "THRIVEBERG_Terminal.exe"

$process = Start-Process -FilePath $setup -ArgumentList @(
    "/VERYSILENT",
    "/SUPPRESSMSGBOXES",
    "/NORESTART",
    "/CLOSEAPPLICATIONS"
) -Wait -PassThru -WindowStyle Hidden

if ($process.ExitCode -ne 0) {
    throw "Installer failed with exit code $($process.ExitCode)."
}
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw "Installed executable was not found at $executable."
}

if (-not $Screenshot) {
    $Screenshot = Join-Path $env:TEMP "thriveberg-installer-smoke.png"
}
$screenshotPath = [IO.Path]::GetFullPath($Screenshot)
$app = Start-Process -FilePath $executable -ArgumentList @(
    "--command",
    "DIAG",
    "--screenshot",
    ('"{0}"' -f $screenshotPath)
) -Wait -PassThru

if ($app.ExitCode -ne 0) {
    throw "Installed application failed with exit code $($app.ExitCode)."
}
if (-not (Test-Path -LiteralPath $screenshotPath -PathType Leaf)) {
    throw "Installed application did not create $screenshotPath."
}

Write-Host "Installed smoke test passed: $screenshotPath" -ForegroundColor Green
