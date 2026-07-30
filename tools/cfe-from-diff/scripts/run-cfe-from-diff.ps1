#Requires -Version 5.1
<#
.SYNOPSIS
  Шаблон запуска cfe-from-diff: git diff → каталог changes → сборка расширения.

.DESCRIPTION
  1. Берёт список изменённых файлов через git diff (диапазон From..To).
  2. Выгружает содержимое файлов на стороне To в staging-каталог --changes.
  3. Запускает cfe-from-diff с указанными параметрами.

  Подставьте значения в блоке «ПАРАМЕТРЫ» и запустите:
    powershell -File scripts\run-cfe-from-diff.ps1
#>

$ErrorActionPreference = "Stop"

# =============================================================================
# ПАРАМЕТРЫ — отредактируйте под свой случай
# =============================================================================

# --- расширение ---
$ExtensionName = "K7_XXXXX"                 # --name
$Purpose       = "Customization"            # Patch | Customization | AddOn
$Prefix        = $null                      # NamePrefix; $null = <name>_

# --- пути ---
# Базовая hierarchical XML-выгрузка CF (то, с чем сравнивает инструмент).
$ConfigDir     = "C:\path\to\cf-dump"

# Git-репозиторий с выгрузкой. Часто совпадает с $ConfigDir.
# Если выгрузка лежит в подкаталоге репо — укажите корень репо и $DumpPrefix.
$GitRepo       = "C:\path\to\cf-dump"
$DumpPrefix    = ""                         # напр. "src/cf/" если dump не в корне репо; иначе ""

# Куда писать XML расширения и .cfe
$OutputDir     = "C:\path\to\extension-src"
$CfePath       = "C:\path\to\K7_XXXXX.cfe"  # не нужен при $SkipBuild = $true

# Staging для --changes (будет очищен и пересобран). Пусто = временный каталог.
$ChangesDir    = ""                         # напр. "C:\temp\cfe-changes"

# --- git diff ---
# Диапазон: файлы, отличающиеся между From и To (как `git diff --name-only From To`).
# Один коммит:  From = "abc1234~1", To = "abc1234"
# От ветки:     From = "origin/main", To = "HEAD"
# От тега:      From = "v1.0.0", To = "HEAD"
$DiffFrom      = "HEAD~1"
$DiffTo        = "HEAD"

# Доп. pathspec для git (фильтр путей). Пусто = весь репозиторий / DumpPrefix.
$Pathspec      = @()                        # напр. @("Catalogs", "CommonModules")

# --- ibcmd (не нужно при SkipBuild) ---
$IbPath        = "C:\path\to\infobase"      # файловая ИБ с уже загруженной базовой CF
$Ibcmd         = $null                      # путь к ibcmd.exe; $null = автопоиск
$IbUser        = $null
$IbPassword    = $null

# --- режим запуска ---
$SkipBuild     = $true                      # только XML; $false — ещё собрать .cfe
$DryRun        = $false                     # только инвентаризация
$ForceOutput   = $false                     # --force (wipe existing --output)
$KeepChanges   = $false                     # не удалять staging после успеха
$ReportPath    = ""                         # JSON-отчёт; "" = не писать
# Список файлов из diff (для отладки). "" = не писать
$ListPath      = ""                         # напр. ".\changed-files.txt"

# Команда запуска CLI. После `pip install -e .` достаточно "cfe-from-diff".
$CfeFromDiff   = "cfe-from-diff"
# Альтернатива без установки:  $CfeFromDiff = @("python", "-m", "cfe_tools.cli")

# =============================================================================
# Логика (обычно менять не нужно)
# =============================================================================

function Assert-GitRepo([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "GitRepo не найден: $Path"
    }
    git -C $Path rev-parse --is-inside-work-tree 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Не git-репозиторий: $Path"
    }
}

function Get-ChangedFiles {
    param(
        [string]$Repo,
        [string]$From,
        [string]$To,
        [string]$Prefix,
        [string[]]$ExtraPathspec
    )

    $specs = @()
    if ($Prefix) {
        $specs += (($Prefix -replace "\\", "/").TrimEnd("/") + "/")
    }
    if ($ExtraPathspec -and $ExtraPathspec.Count -gt 0) {
        $specs += $ExtraPathspec
    }

    # ACMR: added, copied, modified, renamed (удалённые для --changes не нужны)
    $gitArgs = @(
        "-C", $Repo
        "diff", "--name-only", "--diff-filter=ACMR", "-z",
        $From, $To
    )
    if ($specs.Count -gt 0) {
        $gitArgs += "--"
        $gitArgs += $specs
    }

    $raw = & git @gitArgs
    if ($LASTEXITCODE -ne 0) {
        throw "git diff завершился с кодом $LASTEXITCODE"
    }
    if ([string]::IsNullOrEmpty($raw)) {
        return @()
    }

    return @($raw -split "`0" | Where-Object { $_ -ne "" })
}

function Export-BlobToFile {
    param(
        [string]$Repo,
        [string]$ObjectSpec,  # e.g. HEAD:Catalogs/Foo.xml
        [string]$DestPath
    )

    $hash = & git -C $Repo rev-parse $ObjectSpec 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($hash)) {
        return $false
    }

    $destDir = Split-Path -Parent $DestPath
    if (-not (Test-Path -LiteralPath $destDir)) {
        New-Item -ItemType Directory -Path $destDir -Force | Out-Null
    }

    # Бинарно-безопасная выгрузка blob (работает в Windows PowerShell 5.1 и PS 7+)
    $tmp = [IO.Path]::GetTempFileName()
    try {
        $p = Start-Process -FilePath "git" `
            -ArgumentList @("-C", $Repo, "cat-file", "blob", $hash.Trim()) `
            -RedirectStandardOutput $tmp -NoNewWindow -Wait -PassThru
        if ($p.ExitCode -ne 0) {
            return $false
        }
        Copy-Item -LiteralPath $tmp -Destination $DestPath -Force
        return $true
    } finally {
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    }
}

function Export-ChangesTree {
    param(
        [string]$Repo,
        [string]$To,
        [string]$Staging,
        [string]$Prefix,
        [string[]]$RelPaths
    )

    if (Test-Path -LiteralPath $Staging) {
        Remove-Item -LiteralPath $Staging -Recurse -Force
    }
    New-Item -ItemType Directory -Path $Staging | Out-Null

    $prefixNorm = ""
    if ($Prefix) {
        $prefixNorm = ($Prefix -replace "\\", "/").TrimEnd("/") + "/"
    }

    $exported = 0
    foreach ($rel in $RelPaths) {
        $relPosix = ($rel -replace "\\", "/")
        $relInDump = $relPosix
        if ($prefixNorm -and $relPosix.StartsWith($prefixNorm, [StringComparison]::OrdinalIgnoreCase)) {
            $relInDump = $relPosix.Substring($prefixNorm.Length)
        }
        if ([string]::IsNullOrWhiteSpace($relInDump)) { continue }

        $dest = Join-Path $Staging ($relInDump -replace "/", [IO.Path]::DirectorySeparatorChar)
        $ok = Export-BlobToFile -Repo $Repo -ObjectSpec "${To}:${relPosix}" -DestPath $dest
        if (-not $ok) {
            Write-Warning "Пропуск (нет в ${To}): $relPosix"
            continue
        }
        $exported++
    }
    return $exported
}

function Invoke-CfeFromDiff {
    param(
        [object]$Command,   # string или string[]
        [string[]]$CliArgs
    )

    if ($Command -is [System.Array]) {
        $exe = $Command[0]
        $prefix = @()
        if ($Command.Count -gt 1) {
            $prefix = @($Command[1..($Command.Count - 1)])
        }
        & $exe @prefix @CliArgs
        return $LASTEXITCODE
    }

    & ([string]$Command) @CliArgs
    return $LASTEXITCODE
}

# --- main ---

Assert-GitRepo $GitRepo

if (-not (Test-Path -LiteralPath $ConfigDir)) {
    throw "ConfigDir не найден: $ConfigDir"
}

$files = Get-ChangedFiles -Repo $GitRepo -From $DiffFrom -To $DiffTo -Prefix $DumpPrefix -ExtraPathspec $Pathspec
Write-Host "git diff $DiffFrom..$DiffTo : $($files.Count) файл(ов)"

if ($ListPath) {
    $files | Set-Content -LiteralPath $ListPath -Encoding UTF8
    Write-Host "Список записан: $ListPath"
}

if ($files.Count -eq 0) {
    throw "Нет изменённых файлов в диапазоне $DiffFrom..$DiffTo — нечего передавать в cfe-from-diff"
}

$useTemp = [string]::IsNullOrWhiteSpace($ChangesDir)
if ($useTemp) {
    $ChangesDir = Join-Path ([IO.Path]::GetTempPath()) ("cfe-changes-" + [guid]::NewGuid().ToString("N"))
}
Write-Host "Staging --changes: $ChangesDir"

$count = Export-ChangesTree -Repo $GitRepo -To $DiffTo -Staging $ChangesDir -Prefix $DumpPrefix -RelPaths $files
Write-Host "Выгружено в staging: $count"
if ($count -eq 0) {
    throw "Не удалось выгрузить ни одного файла в staging"
}

$cli = @(
    "--name", $ExtensionName
    "--config", $ConfigDir
    "--changes", $ChangesDir
    "--output", $OutputDir
    "--purpose", $Purpose
)
if ($Prefix) { $cli += @("--prefix", $Prefix) }
if ($SkipBuild) {
    $cli += "--skip-build"
} else {
    if ([string]::IsNullOrWhiteSpace($CfePath)) { throw "Укажите `$CfePath или `$SkipBuild = `$true" }
    if ([string]::IsNullOrWhiteSpace($IbPath)) { throw "Укажите `$IbPath или `$SkipBuild = `$true" }
    $cli += @("--cfe", $CfePath, "--ib-path", $IbPath)
    if ($Ibcmd) { $cli += @("--ibcmd", $Ibcmd) }
    if ($IbUser) { $cli += @("--user", $IbUser) }
    if ($IbPassword) { $cli += @("--password", $IbPassword) }
}
if ($DryRun) { $cli += "--dry-run" }
if ($ForceOutput) { $cli += "--force" }
if ($ReportPath) { $cli += @("--report", $ReportPath) }

$cliForLog = @()
for ($i = 0; $i -lt $cli.Count; $i++) {
    if ($cli[$i] -eq "--password" -and ($i + 1) -lt $cli.Count) {
        $cliForLog += @("--password", "***")
        $i++
        continue
    }
    if ($cli[$i] -like "--password=*") {
        $cliForLog += "--password=***"
        continue
    }
    $cliForLog += $cli[$i]
}
Write-Host "Запуск: $CfeFromDiff $($cliForLog -join ' ')"
$exit = Invoke-CfeFromDiff -Command $CfeFromDiff -CliArgs $cli

if ($useTemp -and -not $KeepChanges) {
    Remove-Item -LiteralPath $ChangesDir -Recurse -Force -ErrorAction SilentlyContinue
} else {
    Write-Host "Каталог changes сохранён: $ChangesDir"
}

exit $exit
