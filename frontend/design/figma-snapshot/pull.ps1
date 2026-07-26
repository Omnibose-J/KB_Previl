# Refresh the Figma snapshot: re-download the file tree, re-render frame PNGs,
# and regenerate spec.md. Run this after the Figma board/design file changes.
#
#   powershell -File pull.ps1
#
# Requires a Figma personal access token with scope file_content:read.
# Token is read from -TokenPath (default C:\Users\sobeo\.figma\token.md);
# the first line of 20+ non-space characters is used. Never commit the token.
param(
    [string]$TokenPath = "$env:USERPROFILE\.figma\token.md",
    [string]$FileKey = '4ijHTxrCJ4g30p6TZDwoJB'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not (Test-Path $TokenPath)) { throw "Figma token file not found: $TokenPath" }
$token = ((Get-Content $TokenPath -Raw) -split "`n" |
    Where-Object { $_.Trim() -match '^\S{20,}$' } |
    Select-Object -First 1).Trim()
if (-not $token) { throw "No token-like line in $TokenPath" }
$headers = @{ 'X-Figma-Token' = $token }

Write-Output 'fetching file tree...'
$resp = Invoke-WebRequest "https://api.figma.com/v1/files/$FileKey" -Headers $headers -UseBasicParsing
[IO.File]::WriteAllText("$root\design.json", $resp.Content, [Text.Encoding]::UTF8)
Write-Output ("  design.json  " + (Get-Item "$root\design.json").Length + " bytes")

# Frame id -> render filename. Update when screens are added to the design file.
$frames = [ordered]@{
    '2:2' = 'S1_landing'
    '5:2' = 'S2_input'
    '7:2' = 'S3_results'
    '9:2' = 'S4_detail'
}

Write-Output 'rendering frames...'
New-Item -ItemType Directory -Force "$root\renders" | Out-Null
$ids = ($frames.Keys -join ',')
$images = Invoke-RestMethod "https://api.figma.com/v1/images/$FileKey`?ids=$ids&format=png&scale=1" -Headers $headers
foreach ($id in $frames.Keys) {
    $url = $images.images.$id
    if (-not $url) { Write-Output ("  MISSING render url for " + $id); continue }
    $path = "$root\renders\$($frames[$id]).png"
    Invoke-WebRequest $url -OutFile $path -UseBasicParsing
    Write-Output ('  {0,-12} {1} bytes' -f $frames[$id], (Get-Item $path).Length)
}

Write-Output 'extracting spec...'
& powershell -NoProfile -ExecutionPolicy Bypass -File "$root\extract.ps1" -JsonPath "$root\design.json" -OutPath "$root\spec.md"

Write-Output ''
Write-Output 'done. ../tokens/tokens.json is hand-curated - review it against the new'
Write-Output 'palette and type-scale sections at the bottom of spec.md, then run'
Write-Output '  powershell -File ../tokens/build-css.ps1'
