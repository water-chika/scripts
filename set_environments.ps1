param(
    $Root
)

$config = Get-Content $PSScriptRoot/config.json | ConvertFrom-Json

if ($null -eq $Root) {
    $Root = $config.root
}

$prev_paths = $env:PATH -split ';'
$path_table = [ordered]@{}

$relative_paths = $config.relative_paths;

$relative_paths | Foreach-Object {
    $path = "$Root/$_"
    if ($null -eq $path_table[$path]) {
        $path_table[$path] = $True
    }
}

foreach ($path in $prev_paths) {
    $path_table[$path] = $True
}

$env:PATH = $path_table.Keys | Join-String -Separator ';'

foreach ($key in $config.envs.Keys) {
    $env:$key = $config.envs[$key]
}
