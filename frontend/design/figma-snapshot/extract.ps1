# Figma design-file spec extractor.
# Walks the node tree of a saved GET /v1/files/:key response and emits a compact
# per-screen outline plus a global color palette and type scale.
# Usage: powershell -File extract.ps1 -JsonPath design.json -OutPath spec.md
param(
    [Parameter(Mandatory = $true)][string]$JsonPath,
    [Parameter(Mandatory = $true)][string]$OutPath
)

$ErrorActionPreference = 'Stop'
$doc = (Get-Content $JsonPath -Raw -Encoding UTF8 | ConvertFrom-Json).document

$script:sb = New-Object System.Text.StringBuilder
$script:palette = @{}
$script:typescale = @{}
$script:frameLines = @{}

function Add-Line([string]$s) { [void]$script:sb.AppendLine($s) }

function Get-Hex($color, $opacity) {
    if ($null -eq $color) { return $null }
    $r = [int][math]::Round($color.r * 255)
    $g = [int][math]::Round($color.g * 255)
    $b = [int][math]::Round($color.b * 255)
    $hex = '#{0:X2}{1:X2}{2:X2}' -f $r, $g, $b
    $a = 1.0
    if ($null -ne $opacity) { $a = $opacity }
    if ($null -ne $color.a) { $a = $a * $color.a }
    if ($a -lt 0.999) { $hex += (' @{0:N2}' -f $a) }
    return $hex
}

function Get-Fill($node) {
    if ($null -eq $node.fills) { return $null }
    foreach ($f in $node.fills) {
        if ($f.visible -eq $false) { continue }
        if ($f.type -eq 'SOLID') { return Get-Hex $f.color $f.opacity }
        if ($f.type -like 'GRADIENT*') {
            $stops = @()
            foreach ($s in $f.gradientStops) { $stops += (Get-Hex $s.color $null) }
            return ($f.type + ' [' + ($stops -join ' -> ') + ']')
        }
    }
    return $null
}

function Get-Stroke($node) {
    if ($null -eq $node.strokes -or $node.strokes.Count -eq 0) { return $null }
    foreach ($s in $node.strokes) {
        if ($s.visible -eq $false) { continue }
        if ($s.type -eq 'SOLID') {
            $w = 1
            if ($null -ne $node.strokeWeight) { $w = $node.strokeWeight }
            return ((Get-Hex $s.color $s.opacity) + ' ' + $w + 'px')
        }
    }
    return $null
}

function Get-Layout($node) {
    $bits = @()
    if ($node.layoutMode -and $node.layoutMode -ne 'NONE') {
        $dir = if ($node.layoutMode -eq 'HORIZONTAL') { 'row' } else { 'col' }
        $bits += $dir
        if ($node.itemSpacing) { $bits += ('gap ' + [int]$node.itemSpacing) }
        $pt = [int]$node.paddingTop; $pr = [int]$node.paddingRight
        $pb = [int]$node.paddingBottom; $pl = [int]$node.paddingLeft
        if ($pt -or $pr -or $pb -or $pl) { $bits += ("pad $pt/$pr/$pb/$pl") }
        if ($node.primaryAxisAlignItems) { $bits += ('main:' + $node.primaryAxisAlignItems) }
        if ($node.counterAxisAlignItems) { $bits += ('cross:' + $node.counterAxisAlignItems) }
    }
    if ($null -ne $node.cornerRadius -and $node.cornerRadius -gt 0) { $bits += ('r' + [int]$node.cornerRadius) }
    if ($bits.Count -eq 0) { return $null }
    return ($bits -join ', ')
}

function Walk($node, [int]$depth) {
    $pad = '  ' * $depth
    $meta = @()

    $box = $node.absoluteBoundingBox
    if ($box) { $meta += ('{0}x{1}' -f [int]$box.width, [int]$box.height) }

    $fill = Get-Fill $node
    if ($fill) {
        $meta += ('fill ' + $fill)
        if ($fill -notlike 'GRADIENT*') { $script:palette[$fill] = 1 + $script:palette[$fill] }
    }

    $stroke = Get-Stroke $node
    if ($stroke) { $meta += ('stroke ' + $stroke) }

    $layout = Get-Layout $node
    if ($layout) { $meta += $layout }

    if ($node.type -eq 'TEXT') {
        $st = $node.style
        if ($st) {
            $key = '{0} {1}px w{2}' -f $st.fontFamily, [int]$st.fontSize, $st.fontWeight
            $meta += $key
            $script:typescale[$key] = 1 + $script:typescale[$key]
            if ($st.textAlignHorizontal -and $st.textAlignHorizontal -ne 'LEFT') { $meta += $st.textAlignHorizontal }
            if ($st.lineHeightPx) { $meta += ('lh ' + [int]$st.lineHeightPx) }
        }
        $txt = ($node.characters -replace "\r?\n", ' | ')
        if ($txt.Length -gt 160) { $txt = $txt.Substring(0, 160) + '...' }
        Add-Line ('{0}- TEXT "{1}"   [{2}]' -f $pad, $txt, ($meta -join ', '))
    }
    else {
        $label = '{0}- {1} "{2}"' -f $pad, $node.type, $node.name
        if ($meta.Count -gt 0) { $label += ('   [' + ($meta -join ', ') + ']') }
        Add-Line $label
    }

    # Vector innards carry no spec value.
    if ($node.type -in @('VECTOR', 'BOOLEAN_OPERATION', 'STAR', 'LINE', 'ELLIPSE', 'REGULAR_POLYGON')) { return }
    foreach ($c in $node.children) { Walk $c ($depth + 1) }
}

foreach ($page in $doc.children) {
    Add-Line ('# PAGE: ' + $page.name)
    Add-Line ''
    foreach ($top in $page.children) {
        if ($top.type -ne 'FRAME') { continue }
        $before = $script:sb.Length
        Add-Line ('## ' + $top.name + '   (' + $top.id + ')')
        Add-Line ''
        Walk $top 0
        Add-Line ''
        $script:frameLines[$top.name] = $script:sb.Length - $before
    }
}

Add-Line '# COLOR PALETTE (by usage count)'
Add-Line ''
foreach ($kv in ($script:palette.GetEnumerator() | Sort-Object Value -Descending)) {
    Add-Line ('- {0}   x{1}' -f $kv.Key, $kv.Value)
}
Add-Line ''
Add-Line '# TYPE SCALE (by usage count)'
Add-Line ''
foreach ($kv in ($script:typescale.GetEnumerator() | Sort-Object Value -Descending)) {
    Add-Line ('- {0}   x{1}' -f $kv.Key, $kv.Value)
}

[IO.File]::WriteAllText($OutPath, $script:sb.ToString(), (New-Object System.Text.UTF8Encoding $true))

Write-Output ('spec written: ' + $OutPath)
Write-Output ('total lines : ' + (($script:sb.ToString() -split "`n").Count))
Write-Output ('colors      : ' + $script:palette.Count)
Write-Output ('type styles : ' + $script:typescale.Count)
foreach ($kv in $script:frameLines.GetEnumerator()) { Write-Output ('  chars ' + $kv.Value + '  ' + $kv.Key) }
