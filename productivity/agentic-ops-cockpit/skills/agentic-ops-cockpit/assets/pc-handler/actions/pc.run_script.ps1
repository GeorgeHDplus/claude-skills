# pc.run_script — startet ein Skript aus der Handler-eigenen Skript-Map.
# Doppelte Whitelist (Guard-Regel 1, zwei Locations): Der Worker validiert den
# Namen bereits gegen ein enum; hier wird NOCHMAL gegen $Config.scripts geprueft.
# Es wird nur ein benanntes Skript gestartet — nie Freitext, nie ein uebergebener Pfad.
param($Params, $Config)

$name = [string]$Params.script
if (-not $name) { return @{ status = 'rejected'; error = 'script_missing' } }

$entry = $Config.scripts.PSObject.Properties | Where-Object { $_.Name -eq $name } | Select-Object -First 1
if (-not $entry) { return @{ status = 'rejected'; error = 'not_in_handler_map'; script = $name } }

$path = [System.Environment]::ExpandEnvironmentVariables([string]$entry.Value)
if (-not (Test-Path $path)) { return @{ status = 'error'; error = 'script_path_missing'; script = $name } }

# Detached starten — kann Minuten laufen, darf den 15s-Rahmen nicht sprengen.
$ext = [System.IO.Path]::GetExtension($path).ToLower()
if ($ext -eq '.py') {
    Start-Process -FilePath 'python' -ArgumentList @("`"$path`"") -WindowStyle Hidden | Out-Null
} else {
    Start-Process -FilePath 'powershell' `
        -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$path`"") `
        -WindowStyle Hidden | Out-Null
}

@{ status = 'started'; script = $name }
