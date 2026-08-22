<#
  Agentic Ops Cockpit — Cloudflare-Tunnel-Setup (Windows).

  Richtet den ausgehenden Tunnel vom PC-Handler (127.0.0.1:8787) zu einem
  Cloudflare-Hostname ein und installiert cloudflared als Autostart-Dienst.
  Idempotent: legt Tunnel/Route nur an, wenn sie fehlen.

  NACH diesem Skript fehlt noch die Zugangskontrolle: eine Cloudflare Access
  Application mit Service-Token-Policy vor dem Hostname — das ist der
  Sicherheitskern und wird im Dashboard/API gesetzt, siehe
  references/cloudflare_tunnel.md, Abschnitt "Cloudflare Access".

  Voraussetzung: cloudflared installiert
    winget install --id Cloudflare.cloudflared
  und eine Domain (Zone) in deinem Cloudflare-Account.

  Aufruf (User-Rechte fuer Login/Create; Dienst-Install fragt nach Elevation):
    .\setup-cloudflared.ps1 -Hostname cockpit-pc.example.com
    .\setup-cloudflared.ps1 -Hostname cockpit-pc.example.com -TunnelName cockpit-pc -HandlerPort 8787
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $Hostname,
    [string] $TunnelName = "cockpit-pc",
    [int]    $HandlerPort = 8787
)

$ErrorActionPreference = 'Stop'
$cfDir = Join-Path $env:USERPROFILE '.cloudflared'
New-Item -ItemType Directory -Force -Path $cfDir | Out-Null

function Assert-Cloudflared {
    if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
        throw "cloudflared nicht gefunden. Installieren: winget install --id Cloudflare.cloudflared"
    }
}

Assert-Cloudflared

# Native Executables setzen unter PowerShell 5.1 KEINE terminating errors bei
# Nonzero-Exit (auch nicht mit $ErrorActionPreference='Stop'). Daher nach jedem
# cloudflared-Aufruf $LASTEXITCODE pruefen — sonst meldet das Skript faelschlich
# "Tunnel steht", obwohl ein Schritt fehlschlug.
function Test-CfdExit {
    param([Parameter(Mandatory)][string]$What, [switch]$Tolerant)
    if ($LASTEXITCODE -ne 0) {
        if ($Tolerant) {
            Write-Host "  ${What}: exit $LASTEXITCODE — toleriert (vermutlich bereits vorhanden)." -ForegroundColor DarkGray
        } else {
            throw "${What} schlug fehl (cloudflared exit $LASTEXITCODE)."
        }
    }
}

# 1. Login (oeffnet Browser; Zone auswaehlen). cert.pem landet in $cfDir.
if (-not (Test-Path (Join-Path $cfDir 'cert.pem'))) {
    Write-Host "Login noetig — Browser oeffnet sich, waehle die Zone von $Hostname ..." -ForegroundColor Cyan
    cloudflared tunnel login
    Test-CfdExit 'tunnel login'
} else {
    Write-Host "cert.pem vorhanden — Login uebersprungen." -ForegroundColor DarkGray
}

# 2. Tunnel anlegen (nur falls nicht vorhanden).
$existing = (cloudflared tunnel list --output json | ConvertFrom-Json) |
    Where-Object { $_.name -eq $TunnelName } | Select-Object -First 1
if ($existing) {
    $tunnelId = $existing.id
    Write-Host "Tunnel '$TunnelName' existiert bereits (ID $tunnelId)." -ForegroundColor DarkGray
} else {
    Write-Host "Lege Tunnel '$TunnelName' an ..." -ForegroundColor Cyan
    cloudflared tunnel create $TunnelName | Out-Null
    Test-CfdExit 'tunnel create'
    $tunnelId = ((cloudflared tunnel list --output json | ConvertFrom-Json) |
        Where-Object { $_.name -eq $TunnelName } | Select-Object -First 1).id
}
if (-not $tunnelId) { throw "Konnte Tunnel-ID nicht ermitteln." }

# 3. config.yml aus Template befuellen. credentials-file wird als GANZE Zeile
#    gesetzt (robust gegen Pfad-Sonderzeichen), nicht per Pfad-Regex gepatcht.
$template = Join-Path $PSScriptRoot 'config.example.yml'
$configOut = Join-Path $cfDir 'config.yml'
$creds = Join-Path $cfDir "$tunnelId.json"
$content = Get-Content $template -Raw
$content = $content -replace 'REPLACE_WITH_TUNNEL_ID', $tunnelId
$content = $content -replace 'cockpit-pc\.example\.com', $Hostname
$content = $content -replace 'http://127\.0\.0\.1:8787', "http://127.0.0.1:$HandlerPort"
$content = $content -replace '(?m)^credentials-file:.*$', "credentials-file: $creds"
Set-Content -Path $configOut -Value $content -Encoding UTF8
Write-Host "config.yml geschrieben: $configOut" -ForegroundColor Green

# 4. DNS-Route (CNAME auf den Tunnel). Bei bestehender Route endet cloudflared
#    mit Nonzero — das ist tolerierbar (idempotent).
Write-Host "Setze DNS-Route $Hostname -> Tunnel ..." -ForegroundColor Cyan
cloudflared tunnel route dns $TunnelName $Hostname | Out-Null
Test-CfdExit 'tunnel route dns' -Tolerant

# 5. Ingress validieren — ein Fehler hier ist ECHT (falsche config), also werfen.
cloudflared tunnel ingress validate --config $configOut
Test-CfdExit 'tunnel ingress validate'

# 6. Als Dienst installieren (Autostart). Braucht Admin -> in elevated Shell erneut aufrufen.
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
          ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($isAdmin) {
    Write-Host "Installiere cloudflared als Dienst (Autostart) ..." -ForegroundColor Cyan
    cloudflared service install
    Test-CfdExit 'service install' -Tolerant   # bereits installiert -> Nonzero ok
    Start-Service cloudflared -ErrorAction SilentlyContinue
} else {
    Write-Host "Dienst-Installation uebersprungen (kein Admin)." -ForegroundColor Yellow
    Write-Host "Fuer Autostart einmal in einer Admin-Shell:  cloudflared service install" -ForegroundColor Yellow
    Write-Host "Oder zum Testen im Vordergrund:  cloudflared tunnel run $TunnelName" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Tunnel steht: https://$Hostname -> http://127.0.0.1:$HandlerPort" -ForegroundColor Green
Write-Host "NAECHSTER SCHRITT (Pflicht): Cloudflare Access Service Token vor $Hostname" -ForegroundColor Yellow
Write-Host "  -> references/cloudflare_tunnel.md, Abschnitt 'Cloudflare Access'." -ForegroundColor Yellow
