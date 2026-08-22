<#
  Agentic Ops Cockpit — PC-Handler (Windows).

  Gegenstelle des Cloudflare Workers: nimmt HMAC-signierte Whitelist-Aktionen
  entgegen und fuehrt sie mit User-Rechten aus. Laeuft hinter einem Cloudflare
  Tunnel auf 127.0.0.1 — kein offener Port.

  Guard-Block (redundant zum Worker, Regel-zu-Code):
    1 Kein RCE      — nur Slugs aus $ALLOWED (Datei actions/<slug>.ps1 muss existieren)
    3 Nicht destruktiv — Handler ruft nur benannte Whitelist-Skripte, nie Freitext
    5 HMAC-Pflicht  — jede Anfrage signiert (lib/hmac.ps1), sonst 401
    7 Audit-Log     — jede Anfrage nach logs/handler.log (ohne Secrets/Body)
    8 Kill-Switch   — Datei %COCKPIT_HOME%\KILL -> 503 auf alles

  Start: START-HIER.bat (User-Rechte, NICHT als Admin).
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $Root 'lib\hmac.ps1')

# --- Config laden ----------------------------------------------------------
$ConfigPath = Join-Path $Root 'config.json'
if (-not (Test-Path $ConfigPath)) {
    Write-Host "config.json fehlt. Kopiere config.example.json -> config.json und trage deine Werte ein." -ForegroundColor Red
    exit 1
}
$Config = Get-Content $ConfigPath -Raw | ConvertFrom-Json

$Port           = if ($Config.port) { [int]$Config.port } else { 8787 }
$HmacWindow     = if ($Config.hmac_window_seconds) { [int]$Config.hmac_window_seconds } else { 90 }
$CockpitHome    = [System.Environment]::ExpandEnvironmentVariables($Config.cockpit_home)
if (-not $CockpitHome) { $CockpitHome = Join-Path $env:USERPROFILE 'cockpit' }

$LogDir = Join-Path $CockpitHome 'logs'
$TmpDir = Join-Path $CockpitHome 'tmp'
New-Item -ItemType Directory -Force -Path $LogDir, $TmpDir | Out-Null
$LogFile   = Join-Path $LogDir 'handler.log'
$KillFile  = Join-Path $CockpitHome 'KILL'
$SecretKey = Join-Path $CockpitHome 'secret.key'

# Handler-eigene Whitelist (Guard-Regel 1) — bewusst getrennt von der Worker-Liste.
$ALLOWED = @('pc.status', 'pc.sleep', 'pc.run_script', 'pc.screenshot')

function Write-Log {
    param([hashtable]$Fields)
    $Fields['ts'] = [DateTimeOffset]::UtcNow.ToString('o')
    # Keine Secrets, keine Body-Inhalte — nur trace_id, action, verdict, Dauer.
    ($Fields | ConvertTo-Json -Compress) | Add-Content -Path $LogFile -Encoding UTF8
}

function Send-Json {
    param($Context, [int]$Code, $Obj)
    $json  = $Obj | ConvertTo-Json -Depth 6 -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    $Context.Response.StatusCode = $Code
    $Context.Response.ContentType = 'application/json; charset=utf-8'
    $Context.Response.ContentLength64 = $bytes.Length
    $Context.Response.OutputStream.Write($bytes, 0, $bytes.Length)
    $Context.Response.OutputStream.Close()
}

# secret.key wird pro Request FRISCH gelesen (nicht beim Start gecacht), damit
# eine HMAC-Rotation ohne Handler-Neustart greift — so wie security_model.md es
# zusagt. Der Datei-Read pro Request ist bei diesem Volumen vernachlaessigbar.
function Get-CurrentSecret {
    if (-not (Test-Path $SecretKey)) { return $null }
    return (Get-Content $SecretKey -Raw).Trim()
}

# --- Sicherheits-Checks beim Start ----------------------------------------
if (-not (Test-Path $SecretKey)) {
    Write-Host "secret.key fehlt unter $SecretKey — mit generate_secrets.py erzeugen (PC_HMAC_SECRET)." -ForegroundColor Red
    exit 1
}

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
          ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($isAdmin) {
    # Guard: User-Rechte reichen. Admin ist ein Anti-Pattern — laut warnen, aber laufen.
    Write-Host "WARNUNG: Handler laeuft mit Admin-Rechten. Georges Standard sind User-Rechte." -ForegroundColor Yellow
    Write-Log @{ event = 'admin_warning' }
}

# --- Listener --------------------------------------------------------------
# HttpListener nutzt HTTP.sys; ein normaler User kann das Prefix nur binden, wenn
# einmalig eine URL-ACL reserviert wurde. Fehlt sie, wirft Start() 'access
# denied' — dann den genauen netsh-Befehl ausgeben statt kryptisch abzubrechen.
$listener = [System.Net.HttpListener]::new()
$listener.Prefixes.Add("http://127.0.0.1:$Port/")
try {
    $listener.Start()
} catch [System.Net.HttpListenerException] {
    $acct = "$env:USERDOMAIN\$env:USERNAME"
    Write-Host "HttpListener konnte http://127.0.0.1:$Port/ nicht binden (URL-ACL fehlt)." -ForegroundColor Red
    Write-Host "Einmalig in einer ADMIN-Shell reservieren (nur fuer dich):" -ForegroundColor Yellow
    Write-Host "  netsh http add urlacl url=http://127.0.0.1:$Port/ user=$acct" -ForegroundColor Yellow
    Write-Host "Danach START-HIER.bat erneut ausfuehren (ohne Admin)." -ForegroundColor Yellow
    Write-Log @{ event = 'listener_bind_failed'; error = $_.Exception.Message }
    exit 1
}
Write-Host "Cockpit-Handler laeuft auf http://127.0.0.1:$Port/  (Strg+C beendet)" -ForegroundColor Green
Write-Log @{ event = 'start'; port = $Port }

try {
    while ($listener.IsListening) {
        $ctx = $listener.GetContext()
        $started = [DateTimeOffset]::UtcNow
        $traceId = '-'
        try {
            $req = $ctx.Request

            # Kill-Switch zuerst — vor allem anderen (Guard-Regel 8).
            if (Test-Path $KillFile) {
                Send-Json $ctx 503 @{ status = 'kill_switch' }
                Write-Log @{ event = 'kill_switch'; verdict = 503 }
                continue
            }

            if ($req.HttpMethod -ne 'POST' -or $req.Url.AbsolutePath -ne '/action') {
                Send-Json $ctx 404 @{ error = 'not_found' }
                continue
            }

            $reader = [System.IO.StreamReader]::new($req.InputStream, [System.Text.Encoding]::UTF8)
            $raw = $reader.ReadToEnd()
            $reader.Close()

            $ts  = $req.Headers['x-cockpit-timestamp']
            $sig = $req.Headers['x-cockpit-signature']

            # Zeitfenster gegen Replay (Guard-Regel 5). HMAC-Fehler ist sonst
            # fast immer Uhrzeit-Drift auf dem PC -> w32tm /resync.
            $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
            if (-not $ts -or [Math]::Abs($now - [int64]$ts) -gt $HmacWindow) {
                Send-Json $ctx 401 @{ error = 'stale_or_missing_timestamp' }
                Write-Log @{ event = 'auth'; verdict = 401; reason = 'timestamp' }
                continue
            }

            $secret = Get-CurrentSecret
            if (-not $secret) {
                Send-Json $ctx 500 @{ status = 'error'; error = 'secret_unavailable' }
                Write-Log @{ event = 'error'; reason = 'secret_missing' }
                continue
            }
            $expected = Get-CockpitHmac -Secret $secret -Message ("{0}.{1}" -f $ts, $raw)
            if (-not $sig -or -not (Test-CockpitHmacEqual -Expected $expected -Actual $sig)) {
                Send-Json $ctx 401 @{ error = 'bad_signature' }
                Write-Log @{ event = 'auth'; verdict = 401; reason = 'signature' }
                continue
            }

            $body = $raw | ConvertFrom-Json
            $action = [string]$body.action
            $traceId = if ($body.trace_id) { [string]$body.trace_id } else { '-' }

            if ($ALLOWED -notcontains $action) {
                Send-Json $ctx 403 @{ status = 'rejected'; error = 'not_in_whitelist'; action = $action }
                Write-Log @{ event = 'action'; trace_id = $traceId; action = $action; verdict = 403 }
                continue
            }

            $actionScript = Join-Path $Root ("actions\{0}.ps1" -f $action)
            if (-not (Test-Path $actionScript)) {
                Send-Json $ctx 501 @{ status = 'error'; error = 'action_not_implemented'; action = $action }
                Write-Log @{ event = 'action'; trace_id = $traceId; action = $action; verdict = 501 }
                continue
            }

            # In-Process-Aufruf. Der Worker deckelt zusaetzlich hart auf 15s
            # (guard.js ACTION_TIMEOUT_MS); lang laufende Skripte startet
            # pc.run_script detached, pc.sleep loest den Suspend verzoegert aus.
            $out = & $actionScript -Params $body.params -Config $Config
            $result = @($out | Where-Object { $_ -is [hashtable] })
            $payload = if ($result.Count -gt 0) { $result[-1] } else { @{ status = 'ok' } }

            Send-Json $ctx 200 $payload
            $ms = [int]([DateTimeOffset]::UtcNow - $started).TotalMilliseconds
            Write-Log @{ event = 'action'; trace_id = $traceId; action = $action; verdict = 200; duration_ms = $ms }
        }
        catch {
            # Fehler killt nie den Listener. Keine internen Details/Secrets nach aussen.
            try { Send-Json $ctx 500 @{ status = 'error'; error = 'handler_exception' } } catch { }
            Write-Log @{ event = 'error'; trace_id = $traceId; error = ($_.Exception.Message) }
        }
    }
}
finally {
    $listener.Stop()
    $listener.Close()
    Write-Log @{ event = 'stop' }
}
