param(
    $Root,
    $ConfigPath = "$PSScriptRoot/config.json"
)

# Prepends the configured directories to PATH for the current session and applies
# the configured environment variables. Dot-source it so the changes survive:
#     . .\set_environments.ps1

if (-not (Test-Path -LiteralPath $ConfigPath)) {
    throw "Config not found: ${ConfigPath}. See config.json.example for the expected shape."
}

$config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json

if ([string]::IsNullOrEmpty($Root)) {
    $Root = $config.root
}
if ([string]::IsNullOrEmpty($Root)) {
    throw "No root given and none set in ${ConfigPath}"
}

# An ordered set: configured paths first, then whatever PATH already had,
# duplicates dropped but original order preserved. Windows treats / and \ alike
# and is case insensitive, so compare on a normalised key but keep the original
# spelling as the value.
$path_table = [ordered]@{}
function Add-Path {
    param([string]$Path)
    if ([string]::IsNullOrEmpty($Path)) {
        return
    }
    $key = ($Path -replace '/', '\').TrimEnd('\').ToLowerInvariant()
    if (-not $path_table.Contains($key)) {
        $path_table[$key] = $Path
    }
}

foreach ($relative in $config.relative_paths) {
    Add-Path -Path "${Root}/${relative}"
}
foreach ($path in ($env:PATH -split ';')) {
    Add-Path -Path $path
}
$env:PATH = ($path_table.Values) -join ';'

# ConvertFrom-Json yields a PSCustomObject, which has no .Keys, and $env:$key is
# not valid syntax - the name has to go through the env: provider.
if ($null -ne $config.envs) {
    foreach ($property in $config.envs.PSObject.Properties) {
        Set-Item -LiteralPath "env:$($property.Name)" -Value $property.Value
    }
}
