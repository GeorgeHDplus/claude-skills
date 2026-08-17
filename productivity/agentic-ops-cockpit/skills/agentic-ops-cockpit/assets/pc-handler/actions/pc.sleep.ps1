# pc.sleep — PC in Standby. Bestaetigungspflichtig (der Worker sendet dies nur
# nach /confirm). Idempotent: mehrfach ausgeloest schadet nicht mehr als einmal.
#
# WICHTIG: SetSuspendState blockiert bis zum WIEDER-Aufwachen. Wuerde man es
# synchron aufrufen, liefe der Worker-Timeout (15s) ab und das iPhone bekaeme
# "Timeout", obwohl es geklappt hat. Daher: verzoegert in einem Job ausloesen,
# damit der Handler SOFORT eine saubere Bestaetigung senden kann.
param($Params, $Config)

$delay = 2
Start-Job -ScriptBlock {
    param($d)
    Start-Sleep -Seconds $d
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.Application]::SetSuspendState(
        [System.Windows.Forms.PowerState]::Suspend, $false, $false) | Out-Null
} -ArgumentList $delay | Out-Null

@{ status = 'scheduled'; action = 'pc.sleep'; in_seconds = $delay }
