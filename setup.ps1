# Installs Ask 2 Learn (A2L): virtual env, dependencies, shortcuts (Desktop, Start menu, autostart), then opens it.
# Run:  powershell -ExecutionPolicy Bypass -File setup.ps1          (install, or update after changes)
#       powershell -ExecutionPolicy Bypass -File setup.ps1 -Yes     (install without the "are you sure?" question)
#       powershell -ExecutionPolicy Bypass -File setup.ps1 -Remove  (remove all shortcuts)
#       powershell -ExecutionPolicy Bypass -File setup.ps1 -Say <key>   (print one text, used by Start A2L.bat)
# Every text comes from lang/<code>.json (English: lang/en.json), names and paths from app.json.
param([switch]$Remove, [switch]$Yes, [string]$Say)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

function Read-Json([string]$path) {
    if (Test-Path $path) { return Get-Content -Raw -Encoding UTF8 $path | ConvertFrom-Json }
    return $null
}

$app = Read-Json (Join-Path $root 'app.json')
$files = $app.files
$identity = $app.identity

# The language: the one picked in the app (settings.json), otherwise the Windows language, otherwise English.
$langDir = Join-Path $root 'lang'
$rootLang = 'en'
$settings = Read-Json (Join-Path (Join-Path $env:APPDATA $identity.data_folder) $files.settings)
$candidates = @()
if ($settings -and $settings.app_language) { $candidates += $settings.app_language }
$candidates += (Get-Culture).TwoLetterISOLanguageName, (Get-UICulture).TwoLetterISOLanguageName, $rootLang
$lang = $candidates | Where-Object { Test-Path (Join-Path $langDir "$_.json") } | Select-Object -First 1
$texts = (Read-Json (Join-Path $langDir "$lang.json")).texts
$rootTexts = (Read-Json (Join-Path $langDir "$rootLang.json")).texts

function Get-Text([string]$key, [hashtable]$vars = @{}) {
    $text = $null
    foreach ($table in $texts, $rootTexts) {
        $prop = $table.PSObject.Properties[$key]
        if ($prop -and $prop.Value) { $text = [string]$prop.Value; break }
    }
    if (-not $text) { return $key }
    # {@other.key} inserts another text, {@other.key:upper} in capitals
    $text = [regex]::Replace($text, '\{@([\w.]+)(?::(upper))?\}', [System.Text.RegularExpressions.MatchEvaluator]{
        param($m)
        $inner = Get-Text $m.Groups[1].Value
        if ($m.Groups[2].Success) { $inner.ToUpper() } else { $inner }
    })
    foreach ($k in $vars.Keys) { $text = $text.Replace('{' + $k + '}', [string]$vars[$k]) }
    return $text
}

if ($Say) {
    Write-Host (Get-Text $Say)
    return
}

$name = Get-Text 'app.name'
$dataFolder = Join-Path $env:APPDATA $identity.data_folder
$shortcuts = [ordered]@{
    Autostart = Join-Path ([Environment]::GetFolderPath('Startup')) "$name.lnk"
    Desktop   = Join-Path ([Environment]::GetFolderPath('Desktop')) "$name.lnk"
    StartMenu = Join-Path ([Environment]::GetFolderPath('Programs')) "$name.lnk"
}
# Shortcuts from versions before the rename.
$legacy = foreach ($folder in 'Startup', 'Desktop', 'Programs') {
    foreach ($old in $identity.legacy_shortcuts) { Join-Path ([Environment]::GetFolderPath($folder)) $old }
}
$mainFile = $files.main

function Stop-RunningCopy {
    $running = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
        Where-Object { $_.CommandLine -and $_.CommandLine -like "*$root*$mainFile*" }
    foreach ($p in $running) {
        Write-Host (Get-Text 'setup.stopping' @{ pid = $p.ProcessId })
        Stop-Process -Id $p.ProcessId -Force
    }
}

if ($Remove) {
    Stop-RunningCopy
    foreach ($path in @($shortcuts.Values) + $legacy) {
        if (Test-Path $path) { Remove-Item $path -Confirm:$false; Write-Host (Get-Text 'setup.removed' @{ path = $path }) }
    }
    Write-Host (Get-Text 'setup.removed_done' @{ folder = $dataFolder })
    return
}

if (-not $Yes) {
    Write-Host ''
    Write-Host ('  ' + (Get-Text 'setup.intro')) -ForegroundColor Cyan
    foreach ($i in 1..4) { Write-Host (Get-Text 'setup.bullet' @{ text = (Get-Text "setup.intro$i") }) }
    Write-Host ''
    $answer = Read-Host ('  ' + (Get-Text 'setup.question'))
    $yesWords = (Get-Text 'setup.yes').Split(',') | ForEach-Object { $_.Trim().ToLower() }
    if ($yesWords -notcontains $answer.Trim().ToLower()) {
        Write-Host ('  ' + (Get-Text 'setup.cancelled'))
        return
    }
}

Stop-RunningCopy

$venv = Join-Path $root $files.venv
$venvPy = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path $venvPy)) {
    Write-Host (Get-Text 'setup.venv')
    py -3 -m venv $venv
}
Write-Host (Get-Text 'setup.deps')
& $venvPy -m pip install --quiet --disable-pip-version-check -r (Join-Path $root $files.requirements)
& $venvPy (Join-Path $root $mainFile) --make-icon

foreach ($path in $legacy) {
    if (Test-Path $path) { Remove-Item $path -Confirm:$false }
}

$pythonw = Join-Path $venv 'Scripts\pythonw.exe'
$mainPy = '"' + (Join-Path $root $mainFile) + '"'
$wsh = New-Object -ComObject WScript.Shell
foreach ($kind in $shortcuts.Keys) {
    $lnk = $wsh.CreateShortcut($shortcuts[$kind])
    $lnk.TargetPath = $pythonw
    # Autostart only puts the tray icon up; the other shortcuts open the window.
    $lnk.Arguments = if ($kind -eq 'Autostart') { "$mainPy --hidden" } else { $mainPy }
    $lnk.WorkingDirectory = $root
    $lnk.IconLocation = Join-Path $root $files.ico
    $lnk.Description = $name
    $lnk.Save()
    Write-Host (Get-Text 'setup.shortcut' @{ kind = (Get-Text "setup.kind.$kind"); path = $shortcuts[$kind] })
}

Start-Process -FilePath $pythonw -ArgumentList $mainPy -WorkingDirectory $root
Write-Host ''
Write-Host (Get-Text 'setup.done') -ForegroundColor Cyan
