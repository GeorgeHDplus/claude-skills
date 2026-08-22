# HMAC-Verifikation — Gegenstueck zu worker/src/guard.js (hmacSign).
# Kontrakt (per Testvektor gegen den echten Worker-Code verifiziert):
#   string_to_sign = "<unix_timestamp>.<roher_request_body>"
#   signature      = hex( HMAC-SHA256( PC_HMAC_SECRET, string_to_sign ) )
# WICHTIG: ueber den ROHEN Body signieren, nie ueber re-serialisiertes JSON
# (sonst Key-Order-Mismatch).

function Get-CockpitHmac {
    param(
        [Parameter(Mandatory)] [string] $Secret,
        [Parameter(Mandatory)] [string] $Message
    )
    $hmac = [System.Security.Cryptography.HMACSHA256]::new([System.Text.Encoding]::UTF8.GetBytes($Secret))
    try {
        $bytes = $hmac.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($Message))
        return (($bytes | ForEach-Object { $_.ToString('x2') }) -join '')
    } finally {
        $hmac.Dispose()
    }
}

# Konstanter Vergleich zweier Hex-Strings — kein frueher Abbruch, kein Timing-Leak.
function Test-CockpitHmacEqual {
    param(
        [Parameter(Mandatory)] [string] $Expected,
        [Parameter(Mandatory)] [string] $Actual
    )
    if ($Expected.Length -ne $Actual.Length) { return $false }
    $diff = 0
    for ($i = 0; $i -lt $Expected.Length; $i++) {
        $diff = $diff -bor ([int][char]$Expected[$i] -bxor [int][char]$Actual[$i])
    }
    return ($diff -eq 0)
}
