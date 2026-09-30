param(
    [string]$ApiKey = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not $ApiKey) {
    Write-Host "Opening the free Finnhub registration page..." -ForegroundColor Cyan
    Start-Process "https://finnhub.io/register"
    $ApiKey = Read-Host "Paste your Finnhub API key"
}

$ApiKey = $ApiKey.Trim()
if (-not $ApiKey) {
    throw "No API key was entered. Nothing was changed."
}

Write-Host "Validating the key with an AAPL quote..." -ForegroundColor Cyan
try {
    $quote = Invoke-RestMethod `
        -Uri "https://finnhub.io/api/v1/quote?symbol=AAPL" `
        -Headers @{ "X-Finnhub-Token" = $ApiKey } `
        -TimeoutSec 15
}
catch {
    throw "Finnhub rejected the request. Check the key and internet connection."
}

if (-not $quote.c -or [double]$quote.c -le 0) {
    throw "The key did not return an entitled AAPL quote. Nothing was changed."
}

$python = Join-Path $root ".venv_gui\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = "python"
}
$ApiKey | & $python -m ajax_terminal.secure_settings set FINNHUB_KEY --stdin
if ($LASTEXITCODE -ne 0) {
    throw "The API key could not be stored securely."
}
Write-Host "Finnhub streaming is encrypted for this Windows user. Restart THRIVEBERG and open GP AAPL." -ForegroundColor Green
