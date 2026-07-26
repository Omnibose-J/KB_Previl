# Create one git worktree per lane so concurrent agents never share a tree.
#
# kb.db (229MB) and pipeline/cache (807MB) are gitignored, so a worktree has no
# copy of them. Rather than duplicating a gigabyte per lane, each worktree gets
# KB_DB / KB_CACHE / KB_ENV pointing back at the primary tree.
#
# Usage:  powershell -File lanes/setup-worktrees.ps1
#         powershell -File lanes/setup-worktrees.ps1 -Remove

param(
    [switch]$Remove,
    [string]$Base = "$PSScriptRoot\..\..\KB-lanes"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path "$PSScriptRoot\.."
$Lanes = @(
    @{ Name = "algo";     Branch = "lane/algorithm" },
    @{ Name = "backend";  Branch = "lane/backend" },
    @{ Name = "frontend"; Branch = "lane/frontend" }
)

Push-Location $Root

if (-not (Test-Path "$Root\.git")) {
    Write-Host "ERROR: not a git repository. Run 'git init' first." -ForegroundColor Red
    Pop-Location; exit 1
}

if ($Remove) {
    foreach ($l in $Lanes) {
        $path = Join-Path $Base $l.Name
        if (Test-Path $path) {
            git worktree remove $path --force
            Write-Host "removed $path"
        }
    }
    git worktree prune
    Pop-Location; exit 0
}

if (-not (Test-Path $Base)) { New-Item -ItemType Directory -Path $Base | Out-Null }

$dbPath    = Join-Path $Root "kb.db"
$cachePath = Join-Path $Root "pipeline\cache"
$envPath   = Join-Path $Root ".env"

foreach ($l in $Lanes) {
    $path = Join-Path $Base $l.Name
    if (Test-Path $path) {
        Write-Host "skip (exists): $path"
        continue
    }
    $exists = git branch --list $l.Branch
    if ($exists) { git worktree add $path $l.Branch }
    else         { git worktree add -b $l.Branch $path }

    # Per-worktree launcher that points at the shared data before doing anything
    $enter = @"
`$env:KB_DB    = "$dbPath"
`$env:KB_CACHE = "$cachePath"
`$env:KB_ENV   = "$envPath"
Set-Location "$path"
Write-Host "lane: $($l.Name)  branch: $($l.Branch)"
Write-Host "KB_DB    = `$env:KB_DB"
Write-Host "KB_CACHE = `$env:KB_CACHE"
"@
    Set-Content -Path (Join-Path $path "enter.ps1") -Value $enter -Encoding utf8
    Write-Host "created $path  ($($l.Branch))"
}

Pop-Location

Write-Host ""
Write-Host "Start a lane with:" -ForegroundColor Cyan
foreach ($l in $Lanes) {
    Write-Host ("  powershell -NoExit -File " + (Join-Path $Base ($l.Name + "\enter.ps1")))
}
Write-Host ""
Write-Host "Shared data is NOT copied. Every lane reads the primary kb.db."
Write-Host "Only lane A writes to it."
