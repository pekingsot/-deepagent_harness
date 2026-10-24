$ErrorActionPreference = 'Stop'
$sourceRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$targetRoot = [IO.Path]::GetFullPath('D:\project\deepagent\deepagent_ddd')
if (-not (Test-Path -LiteralPath $targetRoot -PathType Container)) { throw 'Target directory does not exist' }
$names = @('apps','docs','evals','infra','migrations','scripts','src','tests','.env.example','.gitignore','.python-version','Makefile','pyproject.toml','README.md')
$files = foreach ($name in $names) {
    $sourceItem = Join-Path $sourceRoot $name
    if (-not (Test-Path -LiteralPath $sourceItem)) { throw "Missing source: $name" }
    Get-ChildItem -LiteralPath $sourceItem -File -Recurse | Where-Object { $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and $_.Extension -notin @('.pyc','.pyo') }
}
$plan = foreach ($file in $files) {
    $relative = $file.FullName.Substring($sourceRoot.Length).TrimStart('\','/')
    $destination = [IO.Path]::GetFullPath((Join-Path $targetRoot $relative))
    if (-not $destination.StartsWith($targetRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid destination path' }
    $sourceHash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
    if (Test-Path -LiteralPath $destination) {
        if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash -ne $sourceHash) { throw "Existing file conflicts: $relative" }
    }
    [PSCustomObject]@{ Source = $file.FullName; Destination = $destination; Hash = $sourceHash }
}
foreach ($entry in $plan) {
    if (-not (Test-Path -LiteralPath $entry.Destination)) {
        $parent = Split-Path -Parent $entry.Destination
        [IO.Directory]::CreateDirectory($parent) | Out-Null
        Copy-Item -LiteralPath $entry.Source -Destination $entry.Destination -ErrorAction Stop
    }
}
foreach ($entry in $plan) {
    if ((Get-FileHash -LiteralPath $entry.Destination -Algorithm SHA256).Hash -ne $entry.Hash) { throw "Verification failed: $($entry.Destination)" }
}
Write-Output "Copied and verified $($plan.Count) scaffold files to $targetRoot"
