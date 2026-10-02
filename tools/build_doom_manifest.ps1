param(
    [string]$AssetRoot = "ajax_terminal/games/doom/assets"
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path -LiteralPath $AssetRoot).Path
$runtimeFiles = @(
    Get-ChildItem -LiteralPath (Join-Path $root "engine") -File |
        Where-Object { $_.Extension -in ".exe", ".dll" }
    Get-Item -LiteralPath (Join-Path $root "content/freedoom1.wad")
)

$assets = foreach ($file in ($runtimeFiles | Sort-Object FullName)) {
    if (-not $file.FullName.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Runtime asset escaped the configured asset root: $($file.FullName)"
    }
    $relative = $file.FullName.Substring($root.Length).TrimStart("\", "/").Replace("\", "/")
    [ordered]@{
        path = $relative
        sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        size = $file.Length
    }
}

$manifest = [ordered]@{
    schema = 1
    engine = "Chocolate Doom 3.1.1"
    content = "Freedoom Phase 1 0.13.0"
    assets = @($assets)
}

$target = Join-Path $root "manifest.json"
$json = $manifest | ConvertTo-Json -Depth 4 -Compress
[System.IO.File]::WriteAllText($target, $json + "`n", [System.Text.UTF8Encoding]::new($false))
Write-Host "Wrote $target with $($assets.Count) verified runtime assets."
