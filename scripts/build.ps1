# Builds the add-on zip into dist/ with Blender's extension tools and validates it.
#   scripts/build.ps1 [-Blender <path to blender.exe>]
param(
    [string]$Blender = $(if ($env:JBS_BLENDER) { $env:JBS_BLENDER } else { "C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe" })
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$source = Join-Path $root "jbeam_studio"
$dist = Join-Path $root "dist"
New-Item -ItemType Directory -Force $dist | Out-Null
Get-ChildItem $source -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
$license = Join-Path $source "LICENSE.txt"
Copy-Item (Join-Path $root "LICENSE.txt") $license
try {
    & $Blender --factory-startup --command extension build --source-dir $source --output-dir $dist
} finally {
    Remove-Item $license
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$zip = Get-ChildItem $dist -Filter "jbeam_studio-*.zip" | Sort-Object LastWriteTime | Select-Object -Last 1
& $Blender --factory-startup --command extension validate $zip.FullName
exit $LASTEXITCODE
