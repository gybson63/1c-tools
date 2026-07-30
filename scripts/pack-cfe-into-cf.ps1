#Requires -Version 5.1
<#
.SYNOPSIS
  Упаковывает tools/cfe-into-cf в ZIP для копирования на другой ПК.

.EXAMPLE
  powershell -File scripts\pack-cfe-into-cf.ps1
#>
param(
    [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Src = Join-Path $Root "tools\cfe-into-cf"
if (-not (Test-Path -LiteralPath $Src)) {
    throw "Не найден каталог: $Src"
}

if ([string]::IsNullOrWhiteSpace($OutDir)) {
    $OutDir = Join-Path $Root "dist"
}
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$zip = Join-Path $OutDir "cfe-into-cf-$stamp.zip"
if (Test-Path -LiteralPath $zip) {
    Remove-Item -LiteralPath $zip -Force
}

$temp = Join-Path ([IO.Path]::GetTempPath()) ("cfe-into-pack-" + [guid]::NewGuid().ToString("N"))
try {
    New-Item -ItemType Directory -Path $temp | Out-Null
    $dest = Join-Path $temp "cfe-into-cf"
    Copy-Item -LiteralPath $Src -Destination $dest -Recurse

    $excludeDirs = @("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".venv", "venv", "dist", "build", "*.egg-info")
    Get-ChildItem -LiteralPath $dest -Recurse -Directory -Force |
        Where-Object {
            $name = $_.Name
            foreach ($p in $excludeDirs) {
                if ($name -like $p) { return $true }
            }
            return $false
        } |
        Sort-Object { $_.FullName.Length } -Descending |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }

    Compress-Archive -Path $dest -DestinationPath $zip -Force
    Write-Host "OK: $zip"
} finally {
    Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
}
