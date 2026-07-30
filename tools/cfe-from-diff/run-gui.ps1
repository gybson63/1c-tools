#Requires -Version 5.1
<#
.SYNOPSIS
  Запуск GUI из этой папки (без зависимости от старого pip-пакета).
  Предпочитает pythonw, чтобы не оставлять окно консоли.
#>
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$env:PYTHONPATH = Join-Path $Root "src"
Set-Location -LiteralPath $Root

$pythonw = Get-Command pythonw -ErrorAction SilentlyContinue
if ($pythonw) {
    Start-Process -FilePath $pythonw.Source -ArgumentList (@("-m", "cfe_tools.gui_app") + $args) -WorkingDirectory $Root
    exit 0
}

python -m cfe_tools.gui_app @args
