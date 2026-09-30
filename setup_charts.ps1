$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$candidates = @()

if ($env:AJAX_GUI_PYTHON) {
    $candidates += [PSCustomObject]@{ Exe = $env:AJAX_GUI_PYTHON; Args = @() }
}

$localPython = Join-Path $env:USERPROFILE ".local\bin\python3.14.exe"
if (Test-Path -LiteralPath $localPython) {
    $candidates += [PSCustomObject]@{ Exe = $localPython; Args = @() }
}

foreach ($name in @("python3.14", "python3.13", "python3.12", "python3.11", "python")) {
    $command = Get-Command $name -ErrorAction SilentlyContinue
    if ($command) {
        $candidates += [PSCustomObject]@{ Exe = $command.Source; Args = @() }
    }
}

$launcher = Get-Command "py" -ErrorAction SilentlyContinue
if ($launcher) {
    foreach ($version in @("-3.14-64", "-3.13-64", "-3.12-64", "-3.11-64")) {
        $candidates += [PSCustomObject]@{ Exe = $launcher.Source; Args = @($version) }
    }
}

$python = $null
foreach ($candidate in $candidates) {
    try {
        $probeArgs = @($candidate.Args) + @(
            "-c",
            "import struct,sys; print(f'{sys.version_info.major}.{sys.version_info.minor}|{struct.calcsize(`"P`") * 8}')"
        )
        $probe = (& $candidate.Exe @probeArgs 2>$null | Select-Object -First 1)
        if ($LASTEXITCODE -ne 0 -or -not $probe) {
            continue
        }
        $parts = $probe.Trim().Split("|")
        $versionParts = $parts[0].Split(".")
        $compatible = ([int]$versionParts[0] -eq 3 -and [int]$versionParts[1] -ge 11)
        if ($compatible -and $parts[1] -eq "64") {
            $python = $candidate
            break
        }
    }
    catch {
        continue
    }
}

if (-not $python) {
    throw "AJAX charts require Python 3.11+ x64. Install it or set AJAX_GUI_PYTHON to python.exe."
}

$venv = Join-Path $root ".venv_gui"
if (-not (Test-Path -LiteralPath (Join-Path $venv "Scripts\python.exe"))) {
    $venvArgs = @($python.Args) + @("-m", "venv", $venv)
    & $python.Exe @venvArgs
}

& (Join-Path $venv "Scripts\python.exe") -m pip install -e "${root}[charts]"
Write-Host "AJAX chart runtime ready: $venv" -ForegroundColor Green
