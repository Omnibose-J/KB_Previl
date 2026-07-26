# Generate tokens.css from tokens.json so the two never drift.
# Run after editing tokens.json:  powershell -File build-css.ps1
param(
    [string]$JsonPath,
    [string]$OutPath
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $JsonPath) { $JsonPath = "$root\tokens.json" }
if (-not $OutPath) { $OutPath = "$root\tokens.css" }

$tokens = Get-Content $JsonPath -Raw -Encoding UTF8 | ConvertFrom-Json

$lines = New-Object System.Collections.Generic.List[string]
$count = 0

function Add-Var([string]$name, $value, [switch]$Px) {
    $v = if ($Px) { "${value}px" } else { "$value" }
    $script:count++
    $script:lines.Add(('  --{0}: {1};' -f $name, $v))
}

function Add-Section([string]$title) {
    $script:lines.Add('')
    $script:lines.Add(('  /* ' + $title + ' */'))
}

$lines.Add('/* Design tokens for KB TEO.')
$lines.Add(' * GENERATED from tokens.json by build-css.ps1 - do not edit by hand.')
$lines.Add(' */')
$lines.Add(':root {')

foreach ($group in $tokens.color.PSObject.Properties) {
    Add-Section ('color / ' + $group.Name)
    foreach ($t in $group.Value.PSObject.Properties) {
        Add-Var ('color-' + $group.Name + '-' + $t.Name) $t.Value
    }
}

Add-Section 'font family'
foreach ($t in $tokens.font.family.PSObject.Properties) { Add-Var ('font-family-' + $t.Name) $t.Value }

Add-Section 'font weight'
foreach ($t in $tokens.font.weight.PSObject.Properties) { Add-Var ('font-weight-' + $t.Name) $t.Value }

Add-Section 'type scale (size + matching line-height)'
foreach ($t in $tokens.font.scale.PSObject.Properties) {
    Add-Var ('font-size-' + $t.Name) $t.Value.size -Px
    Add-Var ('line-height-' + $t.Name) $t.Value.lineHeight -Px
}

Add-Section 'radius'
foreach ($t in $tokens.radius.PSObject.Properties) { Add-Var ('radius-' + $t.Name) $t.Value -Px }

Add-Section 'space (4px grid)'
foreach ($t in $tokens.space.PSObject.Properties) { Add-Var ('space-' + $t.Name) $t.Value -Px }

Add-Section 'layout'
Add-Var 'layout-frame-width' $tokens.layout.frameWidth -Px
foreach ($t in $tokens.layout.gutter.PSObject.Properties) { Add-Var ('layout-gutter-' + $t.Name) $t.Value -Px }
foreach ($t in $tokens.layout.column.PSObject.Properties) { Add-Var ('layout-' + $t.Name) $t.Value -Px }

$lines.Add('}')
$lines.Add('')

[IO.File]::WriteAllLines($OutPath, $lines, (New-Object System.Text.UTF8Encoding $true))
Write-Output ('wrote ' + $OutPath)
Write-Output ('css custom properties: ' + $count)
