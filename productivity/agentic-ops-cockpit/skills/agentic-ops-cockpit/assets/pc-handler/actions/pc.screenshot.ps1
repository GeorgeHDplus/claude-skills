# pc.screenshot — Desktop-Screenshot als Base64-JPEG (read-only).
# Base64 ist self-contained: keine R2-/Upload-Infra noetig. Der Worker reicht
# das JSON ans iPhone durch; der Kurzbefehl dekodiert "image_base64" und zeigt
# es via Quick Look. Fuer sehr grosse Screens: max_width skaliert herunter,
# jpeg_quality steuert die Payload-Groesse. R2-presigned-URL waere die Alternative
# (siehe README) — bewusst nicht Default, um Zusatz-Secrets zu vermeiden.
param($Params, $Config)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$idx = 0
if ($null -ne $Params.display) { $idx = [int]$Params.display }
$screens = [System.Windows.Forms.Screen]::AllScreens
if ($idx -lt 0 -or $idx -ge $screens.Count) { $idx = 0 }
$bounds = $screens[$idx].Bounds

$quality  = if ($Config.screenshot.jpeg_quality) { [int]$Config.screenshot.jpeg_quality } else { 70 }
$maxWidth = if ($Config.screenshot.max_width)    { [int]$Config.screenshot.max_width }    else { 1600 }

$shot = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
$g = [System.Drawing.Graphics]::FromImage($shot)
$g.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
$g.Dispose()

# Optional herunterskalieren (verkleinert die Base64-Payload deutlich).
$outBmp = $shot
$w = $bounds.Width; $h = $bounds.Height
if ($bounds.Width -gt $maxWidth) {
    $scale = $maxWidth / $bounds.Width
    $w = $maxWidth
    $h = [int]($bounds.Height * $scale)
    $resized = New-Object System.Drawing.Bitmap $w, $h
    $rg = [System.Drawing.Graphics]::FromImage($resized)
    $rg.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $rg.DrawImage($shot, 0, 0, $w, $h)
    $rg.Dispose()
    $outBmp = $resized
}

# JPEG-Encoder mit Qualitaetsparameter.
$enc = [System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() |
    Where-Object { $_.MimeType -eq 'image/jpeg' } | Select-Object -First 1
$encParams = New-Object System.Drawing.Imaging.EncoderParameters 1
$encParams.Param[0] = New-Object System.Drawing.Imaging.EncoderParameter(
    [System.Drawing.Imaging.Encoder]::Quality, [long]$quality)

$ms = New-Object System.IO.MemoryStream
$outBmp.Save($ms, $enc, $encParams)
$b64 = [Convert]::ToBase64String($ms.ToArray())

$ms.Dispose(); $encParams.Dispose(); $outBmp.Dispose()
if (-not [object]::ReferenceEquals($outBmp, $shot)) { $shot.Dispose() }

@{
    status       = 'ok'
    format       = 'jpeg'
    display      = $idx
    width        = $w
    height       = $h
    image_base64 = $b64
}
